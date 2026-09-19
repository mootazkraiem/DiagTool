using System.Globalization;
using System.Collections.Generic;
using System.ComponentModel;
using System.Collections.ObjectModel;
using System.Linq;
using System.IO;
using CommunityToolkit.Mvvm.Input;
using CommunityToolkit.Mvvm.ComponentModel;
using CANvision.Native.Models;
using CANvision.Native.Services;
using System.Windows.Threading;
using System.Threading.Tasks;
using Newtonsoft.Json;
using Microsoft.Win32;

namespace CANvision.Native.ViewModels;

public sealed class HomeViewModel : SectionViewModel
{
    private readonly DispatcherTimer sequenceTimer;
    private readonly CanLogImportService canLogImportService;
    private readonly PythonApiClient pythonApiClient;
    private int sequenceIndex;
    private bool isAnalysisRunning;
    private double analysisProgressPercent;
    private int analysisProcessedFrames;
    private int analysisTotalFrames;
    private double analysisCurrentScore;
    private string analysisCurrentCanId = "0x000";
    private string selectedAttackType = "NORMAL";
    private string importedReplayName = "NO REPLAY";
    private string analysisStatusText = "READY";
    private readonly string[] sequenceMessages =
    {
        "WAITING FOR REPLAY IMPORT...",
        "READY FOR IDS ANALYSIS",
    };

    private string healthModelText  = "--";
    private string healthLlmText    = "--";
    private string healthUptimeText = "--";
    private string healthFpsText    = "--";
    private bool isChoosingMode = true;
    private bool isLiveConnecting;
    private bool isOfflineImporting;
    private bool backendOnline;
    private bool isSelectingModel;
    private string pendingImportName = string.Empty;
    private string? pendingImportPath;

    public HomeViewModel(
        VehicleDataService vehicleDataService,
        CanLogImportService canLogImportService,
        PythonApiClient pythonApiClient,
        ModelSelectionService modelSelection)
        : base(vehicleDataService, SectionKey.Home)
    {
        this.canLogImportService = canLogImportService;
        this.pythonApiClient = pythonApiClient;
        ModelSelection = modelSelection;

        StartSessionCommand = new RelayCommand(() => VehicleDataService.Start());
        StopSessionCommand = new RelayCommand(() => VehicleDataService.Stop());
        ImportReplayCommand = new AsyncRelayCommand(ImportReplayAsync);
        RunAnalysisCommand = new AsyncRelayCommand(RunPendingAnalysisAsync, () => IsSelectingModel);
        CancelModelSelectionCommand = new RelayCommand(CancelModelSelection);
        ShowOfflineImportCommand = new RelayCommand(() => IsChoosingMode = false);
        BackToChoiceCommand = new RelayCommand(() => IsChoosingMode = true);
        LaunchOnlineDiagnosisCommand = new RelayCommand(
            () => { IsLiveConnecting = true; OnlineDiagnosisRequested?.Invoke(); },
            () => CanStartLive);
        CancelLiveSessionCommand = new RelayCommand(() => IsLiveConnecting = false);

        sequenceTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(1.3) };
        sequenceTimer.Tick += OnSequenceTick;
        sequenceTimer.Start();

        vehicleDataService.AppStateChanged += _ =>
        {
            OnPropertyChanged(nameof(IsLiveSessionActive));
            OnPropertyChanged(nameof(CanDiveIn));
            OnPropertyChanged(nameof(MlStatusText));
            OnPropertyChanged(nameof(ReadinessText));
            OnPropertyChanged(nameof(TotalAlertsText));
            OnPropertyChanged(nameof(DatasetStatusText));
            OnPropertyChanged(nameof(DetectionStatusText));
        };
        vehicleDataService.AlertHistoryUpdated += _ => OnPropertyChanged(nameof(TotalAlertsText));

        _ = RefreshHealthAsync();
        // Poll every 2 s until connected, then keep polling to detect backend restarts.
        var healthCheckTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(2) };
        healthCheckTimer.Tick += async (_, _) => await RefreshHealthAsync().ConfigureAwait(true);
        healthCheckTimer.Start();
    }

    public string HealthModelText
    {
        get => healthModelText;
        private set => SetProperty(ref healthModelText, value);
    }

    public string HealthLlmText
    {
        get => healthLlmText;
        private set => SetProperty(ref healthLlmText, value);
    }

    public string HealthUptimeText
    {
        get => healthUptimeText;
        private set => SetProperty(ref healthUptimeText, value);
    }

    public string HealthFpsText
    {
        get => healthFpsText;
        private set => SetProperty(ref healthFpsText, value);
    }

    private async Task RefreshHealthAsync()
    {
        try
        {
            var h = await pythonApiClient.GetSystemHealthDetailAsync(CancellationToken.None).ConfigureAwait(true);
            var wasOnline = backendOnline;
            backendOnline = h is not null;
            if (h is not null)
            {
                HealthModelText  = h.ModelLoaded ? $"LOADED ({h.ModelClusters} clusters)" : "NOT LOADED";
                HealthLlmText    = string.IsNullOrWhiteSpace(h.LlmProvider) ? "--" : h.LlmProvider.ToUpperInvariant();
                HealthUptimeText = h.UptimeSeconds < 60
                    ? $"{h.UptimeSeconds:F0}s"
                    : $"{h.UptimeSeconds / 60:F0}m {h.UptimeSeconds % 60:F0}s";
                HealthFpsText    = $"{h.LiveFps:F1}";
            }
            if (wasOnline != backendOnline)
            {
                OnPropertyChanged(nameof(BackendStatusText));
                OnPropertyChanged(nameof(CanStartLive));
                LaunchOnlineDiagnosisCommand.NotifyCanExecuteChanged();

                // Do NOT auto-start the live session/simulator here. Starting a live session
                // is an explicit user action (see App.xaml.cs's OnlineDiagnosisRequested
                // handler and StartSessionCommand above) — auto-starting it as soon as the
                // backend becomes reachable would silently unlock all navigation tabs before
                // the user has done anything.
            }
        }
        catch { backendOnline = false; }
    }

    public event Action? AnalysisCompleted;
    public event Action? OnlineDiagnosisRequested;

    public bool IsChoosingMode
    {
        get => isChoosingMode;
        private set => SetProperty(ref isChoosingMode, value);
    }

    public bool IsLiveConnecting
    {
        get => isLiveConnecting;
        private set
        {
            SetProperty(ref isLiveConnecting, value);
            OnPropertyChanged(nameof(CanStartLive));
            LaunchOnlineDiagnosisCommand.NotifyCanExecuteChanged();
        }
    }

    /// <summary>The shared vehicle / AI model selection used by the offline analysis.</summary>
    public ModelSelectionService ModelSelection { get; }

    public IAsyncRelayCommand RunAnalysisCommand { get; }
    public IRelayCommand CancelModelSelectionCommand { get; }

    /// <summary>A file is chosen and waits for the vehicle / AI model to be confirmed.</summary>
    public bool IsSelectingModel
    {
        get => isSelectingModel;
        private set
        {
            if (SetProperty(ref isSelectingModel, value))
                RunAnalysisCommand.NotifyCanExecuteChanged();
        }
    }

    public string PendingImportName
    {
        get => pendingImportName;
        private set => SetProperty(ref pendingImportName, value);
    }

    public bool IsOfflineImporting
    {
        get => isOfflineImporting;
        private set => SetProperty(ref isOfflineImporting, value);
    }

    public bool CanStartLive => backendOnline && !isLiveConnecting;

    public IRelayCommand ShowOfflineImportCommand     { get; }
    public IRelayCommand BackToChoiceCommand          { get; }
    public IRelayCommand LaunchOnlineDiagnosisCommand { get; }
    public IRelayCommand CancelLiveSessionCommand     { get; }

    public IRelayCommand StartSessionCommand { get; }
    public IRelayCommand StopSessionCommand  { get; }
    public IRelayCommand ImportReplayCommand { get; }

    public IReadOnlyList<string> AttackTypeOptions { get; } =
        new[] { "NORMAL", "DOS", "FUZZY", "RPM", "GEAR" };

    public bool IsAnalysisRunning
    {
        get => isAnalysisRunning;
        private set
        {
            if (SetProperty(ref isAnalysisRunning, value))
            {
                OnPropertyChanged(nameof(ReadinessText));
                OnPropertyChanged(nameof(CanDiveIn));
            }
        }
    }

    public double AnalysisProgressPercent
    {
        get => analysisProgressPercent;
        private set
        {
            if (SetProperty(ref analysisProgressPercent, value))
            {
                OnPropertyChanged(nameof(AnalysisProgressText));
                OnPropertyChanged(nameof(CanDiveIn));
            }
        }
    }

    private bool isAnalysisIndeterminate;

    // True while the backend is generating detections and AI explanations —
    // a phase with no real per-frame progress to report, unlike parsing (0-40%)
    // and ML scoring (40-90%) which update incrementally. Percent used to just
    // sit frozen at 90 for however long this took, which looked identical to a
    // hung/broken progress bar. The UI shows a pulsing "still working" state
    // here instead of a number that can't move.
    public bool IsAnalysisIndeterminate
    {
        get => isAnalysisIndeterminate;
        private set => SetProperty(ref isAnalysisIndeterminate, value);
    }

    public int AnalysisProcessedFrames
    {
        get => analysisProcessedFrames;
        private set
        {
            if (SetProperty(ref analysisProcessedFrames, value))
            {
                OnPropertyChanged(nameof(AnalysisFramesText));
            }
        }
    }

    public int AnalysisTotalFrames
    {
        get => analysisTotalFrames;
        private set
        {
            if (SetProperty(ref analysisTotalFrames, value))
            {
                OnPropertyChanged(nameof(AnalysisFramesText));
            }
        }
    }

    public double AnalysisCurrentScore
    {
        get => analysisCurrentScore;
        private set
        {
            if (SetProperty(ref analysisCurrentScore, value))
            {
                OnPropertyChanged(nameof(AnalysisCurrentScoreText));
            }
        }
    }

    public string AnalysisCurrentCanId
    {
        get => analysisCurrentCanId;
        private set => SetProperty(ref analysisCurrentCanId, value);
    }

    public string SelectedAttackType
    {
        get => selectedAttackType;
        set => SetProperty(ref selectedAttackType, string.IsNullOrWhiteSpace(value) ? "NORMAL" : value.ToUpperInvariant());
    }

    public string ImportedReplayName
    {
        get => importedReplayName;
        private set => SetProperty(ref importedReplayName, value);
    }

    public string AnalysisStatusText
    {
        get => analysisStatusText;
        private set => SetProperty(ref analysisStatusText, value);
    }

    public string AnalysisProgressText => $"{AnalysisProgressPercent:F1}%";
    public string AnalysisFramesText => $"{AnalysisProcessedFrames}/{Math.Max(1, AnalysisTotalFrames)}";
    public string AnalysisCurrentScoreText => $"{AnalysisCurrentScore:F2}";

    public string SequenceText => sequenceMessages[sequenceIndex];
    public string ConnectionStatus => ConnectivityText;
    public string LastPacketTime => UpdatedText;
    public int FaultCount => VehicleDataService.CurrentAnomalies?.Count ?? 0;

    // ── Analysis state HUD (replaces fake SOC/Voltage/MotorTemp/Current) ─────

    public string DatasetStatusText =>
        IsLiveSessionActive ? "LIVE SIM" :
        ImportedReplayName == "NO REPLAY" ? "NO DATASET" :
        IsAnalysisRunning ? "IMPORTING" :
        AnalysisProgressPercent >= 100 ? "READY" : "LOADED";

    public string FramesLoadedText =>
        AnalysisTotalFrames == 0 ? "--" : $"{AnalysisTotalFrames:N0}";

    public string MlStatusText =>
        VehicleDataService.AppState == Models.AppState.LiveSession
            ? (VehicleDataService.DetectedAttackType == "NONE" ? "MONITORING" : VehicleDataService.DetectedAttackType)
            : VehicleDataService.AppState == Models.AppState.AnalysisComplete
                ? VehicleDataService.DetectedAttackType
                : VehicleDataService.AppState == Models.AppState.Analyzing
                    ? "ACTIVE"
                    : "--";

    public string DetectionStatusText =>
        VehicleDataService.TotalAlerts > 0
            ? $"{VehicleDataService.TotalAlerts} EVENT(S)"
            : VehicleDataService.AppState == CANvision.Native.Models.AppState.AnalysisComplete
                ? "CLEAN"
                : "--";

    public string BackendStatusText =>
        backendOnline || string.Equals(Snapshot.Source, "python-api", StringComparison.OrdinalIgnoreCase)
            ? "CONNECTED"
            : "OFFLINE";

    public string ReadinessText =>
        IsLiveSessionActive
            ? "LIVE SIMULATION ACTIVE"
            : IsAnalysisRunning
                ? "ANALYSIS RUNNING"
                : ImportedReplayName == "NO REPLAY"
                    ? "IMPORT REPLAY TO BEGIN"
                    : "REPLAY READY";

    // Live session is active when the AppState is LiveSession.
    public bool IsLiveSessionActive =>
        VehicleDataService.AppState == Models.AppState.LiveSession;

    public string TotalAlertsText =>
        VehicleDataService.TotalAlerts == 0 ? "--" : VehicleDataService.TotalAlerts.ToString();

    // Dive In enabled after full offline analysis, or immediately when live session is active.
    public bool CanDiveIn =>
        VehicleDataService.AppState == Models.AppState.LiveSession
        || (!IsAnalysisRunning && ImportedReplayName != "NO REPLAY" && AnalysisProgressPercent >= 100.0);

    public string HomeRibbon => $"{ConnectivityText} | REPLAY {VehicleDataService.ReplayName} | LAST SAMPLE {UpdatedText}";

    private Task ImportReplayAsync()
    {
        var dialog = new OpenFileDialog
        {
            Filter = "Replay CSV (*.csv)|*.csv|MF4 recordings (*.mf4)|*.mf4|CAN logs (*.log;*.asc;*.trc;*.txt)|*.log;*.asc;*.trc;*.txt|All files (*.*)|*.*",
            Title = "Import Replay CSV",
        };

        if (dialog.ShowDialog() != true)
        {
            return Task.CompletedTask;
        }

        // IMPORT -> SELECT MODEL -> RUN ANALYSIS: hold the file until the user confirms
        // the vehicle / AI model; nothing is parsed or analysed yet.
        pendingImportPath = dialog.FileName;
        PendingImportName = Path.GetFileName(dialog.FileName);
        IsSelectingModel = true;
        return Task.CompletedTask;
    }

    private void CancelModelSelection()
    {
        pendingImportPath = null;
        PendingImportName = string.Empty;
        IsSelectingModel = false;
    }

    private async Task RunPendingAnalysisAsync()
    {
        var filePath = pendingImportPath;
        if (string.IsNullOrEmpty(filePath)) return;
        pendingImportPath = null;
        IsSelectingModel = false;
        await RunOfflineImportAsync(filePath!).ConfigureAwait(true);
    }

    private async Task RunOfflineImportAsync(string filePath)
    {
        // The model chosen for this run; changing the selection later does not affect it.
        var analysisModel = ModelSelection.SelectedModel;
        var replayName = Path.GetFileName(filePath);
        ImportedReplayName = replayName;
        AnalysisStatusText = "LOADING DATASET";
        VehicleDataService.Stop();

        IsOfflineImporting = true;

        // A vehicle model scores every frame through the runtime engine, which takes
        // longer than the general engine (about a minute for a 50k-frame log), so it
        // gets a wider window than the general path's 90 s.
        var analyzeSeconds = analysisModel.IsGeneral ? 90 : 420;
        using var analyzeTimeout = new System.Threading.CancellationTokenSource(TimeSpan.FromSeconds(analyzeSeconds));
        try
        {
            // Transparently decode MF4 -> CSV first, then run the exact same
            // parse/analyze/replay path CSV already uses — no separate MF4 code
            // path, no manual conversion by the user.
            var effectiveFilePath = filePath;
            if (Path.GetExtension(filePath).Equals(".mf4", StringComparison.OrdinalIgnoreCase))
            {
                AnalysisStatusText = "CONVERTING MF4";
                var csvPath = await VehicleDataService.ConvertMf4ToCsvAsync(filePath);
                if (string.IsNullOrEmpty(csvPath))
                {
                    AnalysisStatusText = "MF4 CONVERSION FAILED";
                    IsOfflineImporting = false;
                    return;
                }
                effectiveFilePath = csvPath!;
            }

            // Start Python batch analysis in parallel with C# parsing, but only when backend is up.
            // The 90-second CTS above caps the wait so a slow /analyze call never blocks the UI indefinitely.
            var analyzeTask = backendOnline
                ? pythonApiClient.AnalyzeLogsAsync(new[] { effectiveFilePath }, analyzeTimeout.Token, analysisModel.Id)
                : Task.FromResult<PythonAnalyzeResponse?>(null);

            // Parse frames in C# for animation/signal display; skip per-frame HTTP inference
            AnalysisStatusText = "PARSING FRAMES";
            AnalysisProgressPercent = 0;
            var parseProgress = new Progress<double>(pct =>
            {
                AnalysisProgressPercent = Clamp(pct * 0.4, 0, 40); // parse phase = 0–40%
            });

            var parseResult = await Task.Run(
                () => canLogImportService.ParseFileAsync(effectiveFilePath, skipMlScoring: true, parseProgress: parseProgress, cancellationToken: CancellationToken.None),
                CancellationToken.None
            ).ConfigureAwait(true);

            var packets = parseResult.Packets.ToList();
            AnalysisTotalFrames = packets.Count;
            AnalysisProcessedFrames = 0;
            AnalysisProgressPercent = packets.Count > 0 ? 40 : 0;
            AnalysisCurrentScore = 0;
            AnalysisCurrentCanId = "0x000";

            if (packets.Count > 0)
                VehicleDataService.SetAppState(CANvision.Native.Models.AppState.DatasetLoaded);

            VehicleDataService.LoadReplayPackets(replayName, packets);
            VehicleDataService.BeginReplayAnalysis();

            var stopwatch = System.Diagnostics.Stopwatch.StartNew();

            if (packets.Count > 0)
            {
                IsAnalysisRunning = true;
                AnalysisStatusText = $"RUNNING ML ANALYSIS · {analysisModel.ModelLabel}";

                var steps = Math.Max(80, Math.Min(220, packets.Count));
                var delayMs = packets.Count > 12000 ? 12 : 20;

                for (var step = 0; step < steps; step++)
                {
                    var fraction = steps <= 1 ? 1.0 : step / (double)(steps - 1);
                    var index = (int)Math.Round(fraction * (packets.Count - 1));
                    index = Math.Max(0, Math.Min(packets.Count - 1, index));
                    var packet = packets[index];
                    var score = ResolvePacketScore(packet);

                    AnalysisProcessedFrames = index + 1;
                    // animation phase = 40–90%
                    AnalysisProgressPercent = Clamp(40 + ((index + 1) / (double)packets.Count) * 50.0, 40, 90);
                    AnalysisCurrentScore = score;
                    AnalysisCurrentCanId = $"0x{packet.Frame.CanId:X3}";

                    VehicleDataService.PublishPlaybackPacket(packet);
                    var fps = stopwatch.Elapsed.TotalSeconds <= 0
                        ? 0
                        : AnalysisProcessedFrames / stopwatch.Elapsed.TotalSeconds;
                    VehicleDataService.UpdateReplayRuntime(
                        AnalysisProcessedFrames,
                        packet.Frame.CanId,
                        score,
                        fps,
                        VehicleDataService.RuntimeLatencyMs);

                    await Task.Delay(delayMs).ConfigureAwait(true);
                }
            }
            else
            {
                AnalysisStatusText = "NO FRAMES PARSED — WAITING FOR BACKEND ANALYSIS";
            }

            AnalysisStatusText = "GENERATING DETECTIONS";
            AnalysisProgressPercent = 90;
            IsAnalysisIndeterminate = true;
            var analysisResponse = await analyzeTask.ConfigureAwait(true);
            AnalysisStatusText = "BUILDING INTELLIGENCE";
            var metrics = await pythonApiClient.GetMetricsAsync(CancellationToken.None).ConfigureAwait(true);
            var apiDetections = ConvertApiAnomalies(analysisResponse, packets);
            var apiAnomalies = apiDetections.Select(d => d.Anomaly).ToList();
            if (apiAnomalies.Count > 0)
            {
                VehicleDataService.UpdateAnomalies(apiAnomalies);
            }

            var detectedAttack = ResolveAttackType(analysisResponse, apiAnomalies, SelectedAttackType);
            var confidence = ResolveConfidence(analysisResponse, apiAnomalies, packets.Count);

            if (packets.Count > 0)
            {
                var latencyMs = (analysisResponse?.Summary?.ElapsedMs ?? 0) > 0
                    ? analysisResponse!.Summary!.ElapsedMs
                    : (metrics?.AvgAnalyzeLatencyMs ?? stopwatch.Elapsed.TotalMilliseconds);
                var finalFps = stopwatch.Elapsed.TotalSeconds <= 0 ? 0 : packets.Count / stopwatch.Elapsed.TotalSeconds;
                var finalPacket = packets[packets.Count - 1];
                VehicleDataService.UpdateReplayRuntime(
                    packets.Count,
                    finalPacket.Frame.CanId,
                    ResolvePacketScore(finalPacket),
                    finalFps,
                    latencyMs);
            }

            VehicleDataService.CompleteReplayAnalysis(detectedAttack, confidence, apiDetections.Select(d => d.Alert).ToList());
            AnalysisStatusText = $"ANALYSIS COMPLETE — {detectedAttack} · {analysisModel.ModelLabel}";
            AnalysisProgressPercent = 100;
            IsAnalysisIndeterminate = false;
            AnalysisProcessedFrames = packets.Count;
            IsAnalysisRunning = false;
            IsOfflineImporting = false;
            AnalysisCompleted?.Invoke();
        }
        catch (Exception exception)
        {
            IsAnalysisIndeterminate = false;
            IsOfflineImporting = false;
            AnalysisStatusText = $"ANALYSIS FAILED: {exception.Message.ToUpperInvariant()}";
            IsAnalysisRunning = false;
            VehicleDataService.CompleteReplayAnalysis("UNKNOWN", 0, Array.Empty<RuntimeAlertEvent>());
            VehicleDataService.PublishExternalSnapshot(VehicleSnapshot.Default());
        }
    }

    private static double ResolvePacketScore(PlaybackPacket packet)
    {
        if (packet.Anomalies is null || packet.Anomalies.Count == 0)
            return 0;
        var scores = packet.Anomalies
            .Select(item => item.SeverityScore > 0 ? item.SeverityScore / 100.0 : Math.Abs(item.AnomalyScore))
            .ToList();
        return scores.Count == 0 ? 0 : scores.Max();
    }

    // One backend detection, as the anomaly list and the alert history each need it.
    internal sealed class ApiDetection
    {
        public ApiDetection(CanAnomaly anomaly, RuntimeAlertEvent alert)
        {
            Anomaly = anomaly;
            Alert = alert;
        }

        public CanAnomaly Anomaly { get; }
        public RuntimeAlertEvent Alert { get; }
    }

    // Maps /analyze detections to anomalies and alert-history events.
    // context.timestamp is the raw CSV time of the flagged frame, the same value the
    // importer stores as RelativeTimestampSeconds, so each alert takes the wall-clock
    // time of its own frame and lands on the right spot of the replay timeline.
    internal static List<ApiDetection> ConvertApiAnomalies(PythonAnalyzeResponse? response, IReadOnlyList<PlaybackPacket> packets)
    {
        var output = new List<ApiDetection>();
        if (response?.Anomalies is null)
        {
            return output;
        }

        var frameTimes = packets
            .Select(p => (Relative: p.Frame.RelativeTimestampSeconds, Utc: p.Frame.TimestampUtc))
            .OrderBy(t => t.Relative)
            .ToArray();
        var relativeTimes = frameTimes.Select(t => t.Relative).ToArray();

        foreach (var item in response.Anomalies)
        {
            var context = item.Context ?? new Newtonsoft.Json.Linq.JObject();
            var explanation = item.Explanation ?? new Newtonsoft.Json.Linq.JObject();
            var canId = ReadHexOrInt(context, "can_id");
            var score = ReadDouble(context, "anomaly_score", ReadDouble(explanation, "anomaly_score", 0));
            var severityScore = Math.Max(0, Math.Min(100, Math.Abs(score) * 100.0));
            // Same bands the screens label: CRITICAL >= 0.80, WARNING >= 0.55.
            var severity = severityScore >= 80 ? "CRITICAL" : (severityScore >= 55 ? "WARNING" : "INFO");
            var relativeSeconds = ReadDouble(context, "timestamp", 0);

            var layers = context.TryGetValue("detection_layers", StringComparison.OrdinalIgnoreCase, out var layerToken)
                         && layerToken is Newtonsoft.Json.Linq.JArray layerArray
                ? layerArray.Select(t => t.ToString().ToUpperInvariant()).Where(t => t.Length > 0).ToList()
                : new List<string>();
            var layerText = layers.Count > 0 ? string.Join(" + ", layers) : "ML";
            var knownAttack = ReadString(explanation, "kb_match_label", string.Empty);
            var attackType = !string.IsNullOrWhiteSpace(knownAttack)
                ? knownAttack.ToUpperInvariant()
                : ReadString(context, "type", layers.Count > 0 ? layers[0] : "ANOMALY").ToUpperInvariant();
            var topFeature = ReadString(context, "top_feature", string.Empty);
            var description = string.IsNullOrWhiteSpace(topFeature)
                ? $"Layers: {layerText}"
                : $"Layers: {layerText} · top feature {topFeature}";

            // Per-layer scores in the key=value form the Anomaly Intel layer breakdown reads.
            var payloadScore = ReadBool(context, "plausibility_checked") && !ReadBool(context, "plausibility_passed", true) ? 1.0 : 0.0;
            var layerScores = string.Format(
                CultureInfo.InvariantCulture,
                "timing={0:F3}, payload={1:F3}, ml={2:F3}, persistence={3:F3}",
                ReadDouble(context, "timing_score", 0),
                payloadScore,
                Math.Abs(score),
                ReadDouble(context, "temporal_score", 0));

            var timestampUtc = NearestFrameUtc(frameTimes, relativeTimes, relativeSeconds);
            var anomaly = new CanAnomaly
            {
                Code = ReadString(context, "code", "API-ANOMALY"),
                Title = attackType,
                Description = description,
                Severity = severity,
                SeverityScore = severityScore,
                AnomalyScore = score,
                RelatedCanId = canId,
                TimestampUtc = timestampUtc,
                Source = "fastapi",
            };
            var alert = new RuntimeAlertEvent
            {
                TimestampUtc = timestampUtc,
                RelativeSeconds = relativeSeconds,
                CanId = $"0x{canId:X3}",
                Severity = severity,
                Score = Math.Abs(score),
                AttackType = attackType,
                Reason = $"{description}, {layerScores}",
            };
            output.Add(new ApiDetection(anomaly, alert));
        }

        return output;
    }

    // Wall-clock time of the imported frame closest to a raw CSV timestamp.
    private static DateTime NearestFrameUtc((double Relative, DateTime Utc)[] frameTimes, double[] relativeTimes, double relativeSeconds)
    {
        if (frameTimes.Length == 0)
            return DateTime.UtcNow;
        var index = Array.BinarySearch(relativeTimes, relativeSeconds);
        if (index < 0)
        {
            index = ~index;
            if (index >= relativeTimes.Length)
                index = relativeTimes.Length - 1;
            else if (index > 0 && relativeSeconds - relativeTimes[index - 1] < relativeTimes[index] - relativeSeconds)
                index--;
        }
        return frameTimes[index].Utc;
    }

    private static string ResolveAttackType(PythonAnalyzeResponse? response, IReadOnlyList<CanAnomaly> anomalies, string fallback)
    {
        var tokens = new List<string>();
        if (response?.Anomalies is not null)
        {
            foreach (var item in response.Anomalies)
            {
                tokens.Add(ReadString(item.Context ?? new Newtonsoft.Json.Linq.JObject(), "type", string.Empty));
                tokens.Add(ReadString(item.Explanation ?? new Newtonsoft.Json.Linq.JObject(), "issue", string.Empty));
                tokens.Add(ReadString(item.Explanation ?? new Newtonsoft.Json.Linq.JObject(), "reason", string.Empty));
            }
        }

        tokens.AddRange(anomalies.Select(a => $"{a.Title} {a.Description}"));
        var normalized = string.Join(" ", tokens).ToLowerInvariant();
        if (normalized.Contains("dos") || normalized.Contains("flood")) return "DOS";
        if (normalized.Contains("fuzzy") || normalized.Contains("random")) return "FUZZY";
        if (normalized.Contains("rpm") || normalized.Contains("overspeed")) return "RPM";
        if (normalized.Contains("gear") || normalized.Contains("shift")) return "GEAR";
        if (normalized.Contains("normal")) return "NORMAL";
        return string.IsNullOrWhiteSpace(fallback) ? "UNKNOWN" : fallback.ToUpperInvariant();
    }

    private static double ResolveConfidence(PythonAnalyzeResponse? response, IReadOnlyList<CanAnomaly> anomalies, int totalFrames)
    {
        if (response?.Anomalies is not null && response.Anomalies.Count > 0)
        {
            var values = new List<double>();
            foreach (var item in response.Anomalies)
            {
                var confidence = ReadDouble(item.Explanation ?? new Newtonsoft.Json.Linq.JObject(), "confidence", -1);
                if (confidence >= 0)
                {
                    values.Add(confidence <= 1 ? confidence * 100 : confidence);
                }
            }

            if (values.Count > 0)
            {
                return Clamp(values.Average(), 0, 100);
            }
        }

        if (response?.Summary is not null && response.Summary.RowsParsed > 0)
        {
            var ratio = response.Summary.AnomalyCount / (double)Math.Max(1, response.Summary.RowsParsed);
            return Clamp(55 + (ratio * 45), 0, 100);
        }

        if (anomalies.Count > 0)
        {
            return Clamp(anomalies.Average(a => a.SeverityScore), 0, 100);
        }

        return totalFrames > 0 ? 52 : 0;
    }

    private static int ReadHexOrInt(Newtonsoft.Json.Linq.JObject source, string key)
    {
        var text = ReadString(source, key, "0");
        if (text.StartsWith("0x", StringComparison.OrdinalIgnoreCase) &&
            int.TryParse(text.Substring(2), System.Globalization.NumberStyles.HexNumber, System.Globalization.CultureInfo.InvariantCulture, out var hexValue))
        {
            return hexValue;
        }

        if (int.TryParse(text, out var value))
        {
            return value;
        }

        return 0;
    }

    private static double ReadDouble(Newtonsoft.Json.Linq.JObject source, string key, double fallback)
    {
        if (source.TryGetValue(key, StringComparison.OrdinalIgnoreCase, out var token) &&
            double.TryParse(
                token?.ToString(),
                System.Globalization.NumberStyles.Float,
                System.Globalization.CultureInfo.InvariantCulture,
                out var value))
        {
            return value;
        }

        return fallback;
    }

    private static bool ReadBool(Newtonsoft.Json.Linq.JObject source, string key, bool fallback = false)
    {
        if (source.TryGetValue(key, StringComparison.OrdinalIgnoreCase, out var token) &&
            bool.TryParse(token.ToString(), out var value))
        {
            return value;
        }

        return fallback;
    }

    private static string ReadString(Newtonsoft.Json.Linq.JObject source, string key, string fallback)
    {
        if (source.TryGetValue(key, StringComparison.OrdinalIgnoreCase, out var token))
        {
            var text = token?.ToString();
            if (!string.IsNullOrWhiteSpace(text))
            {
                return text!.Trim();
            }
        }

        return fallback;
    }

    private void OnSequenceTick(object? sender, EventArgs e)
    {
        if (sequenceIndex < sequenceMessages.Length - 1)
        {
            sequenceIndex++;
            OnPropertyChanged(nameof(SequenceText));
            OnPropertyChanged(nameof(SectionDescription));
        }
        else
        {
            sequenceTimer.Stop();
        }
    }

    public override string SectionDescription => SequenceText;

    protected override void OnDataUpdated(VehicleSnapshot snapshot)
    {
        base.OnDataUpdated(snapshot);
        OnPropertyChanged(nameof(ReliabilityScore));
        OnPropertyChanged(nameof(ReliabilityScoreText));
        OnPropertyChanged(nameof(ConnectionStatus));
        OnPropertyChanged(nameof(LastPacketTime));
        OnPropertyChanged(nameof(FaultCount));
        OnPropertyChanged(nameof(ReadinessText));
        OnPropertyChanged(nameof(HomeRibbon));
        OnPropertyChanged(nameof(SectionDescription));
        OnPropertyChanged(nameof(AnalysisProgressText));
        OnPropertyChanged(nameof(AnalysisFramesText));
        OnPropertyChanged(nameof(AnalysisCurrentScoreText));
        OnPropertyChanged(nameof(BackendStatusText));
        OnPropertyChanged(nameof(CanStartLive));
        LaunchOnlineDiagnosisCommand.NotifyCanExecuteChanged();
    }
}

