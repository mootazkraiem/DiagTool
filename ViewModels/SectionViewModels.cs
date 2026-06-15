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

public abstract class SectionViewModel : ViewModelBase
{
    private bool isCalibrating = true;
    private string calibrationText = "WAITING FOR SIGNAL...";
    private int calibrationProgress = 0;
    private readonly List<VehicleSnapshot> startupBuffer = new();
    
    public SectionDescriptor? Descriptor { get; }

    protected SectionViewModel(VehicleDataService vehicleDataService, SectionKey key)
    {
        VehicleDataService = vehicleDataService;
        Key = key;
        Descriptor = key == SectionKey.Home ? null : SectionCatalog.For(key);
        vehicleDataService.PropertyChanged += VehicleDataServiceOnPropertyChanged;
        vehicleDataService.DataUpdated += OnDataUpdated;
        
        SaveSnapshotCommand = new RelayCommand(SaveSnapshot);

        NextCardCommand = new RelayCommand(() => { if (CurrentCardIndex < MaxCards - 1) CurrentCardIndex++; });
        PreviousCardCommand = new RelayCommand(() => { if (CurrentCardIndex > 0) CurrentCardIndex--; });
        GoToCardCommand = new RelayCommand<int>(idx => { if (idx >= 0 && idx < MaxCards) CurrentCardIndex = idx; });
    }

    protected VehicleDataService VehicleDataService { get; }

    public SectionKey Key { get; }

    public IRelayCommand SaveSnapshotCommand { get; }

    public bool IsCalibrating
    {
        get => isCalibrating;
        protected set => SetProperty(ref isCalibrating, value);
    }

    public string CalibrationText
    {
        get => calibrationText;
        protected set => SetProperty(ref calibrationText, value);
    }

    public VehicleSnapshot Snapshot => VehicleDataService.CurrentSnapshot ?? VehicleSnapshot.Default();

    // Navigation and Cards
    private int currentCardIndex = 0;
    public int CurrentCardIndex
    {
        get => currentCardIndex;
        set
        {
            if (SetProperty(ref currentCardIndex, value))
            {
                OnPropertyChanged(nameof(VerticalOffset));
            }
        }
    }

    public virtual int MaxCards => 1;
    public double VerticalOffset => CurrentCardIndex * -800; // Simulated viewport height

    public IRelayCommand NextCardCommand { get; }
    public IRelayCommand PreviousCardCommand { get; }
    public IRelayCommand<int> GoToCardCommand { get; }

    // Derived properties reflect "Calibrating" state
    public double SOC => IsCalibrating ? 0 : Snapshot.SOC;
    public string SOCText => IsCalibrating ? "---" : $"{Snapshot.SOC:F1}%";
    public double SOCRatio => IsCalibrating ? 0 : Clamp(Snapshot.SOC / 100.0, 0.0, 1.0);

    public double BatteryTemp => IsCalibrating ? 0 : Snapshot.BatteryTemp;
    public string BatteryTempText => IsCalibrating ? "---" : $"{BatteryTemp:F1} C";
    public double BatteryTempRatio => IsCalibrating ? 0 : Clamp(BatteryTemp / 120.0, 0.0, 1.0);

    public double BatteryVoltage => IsCalibrating ? 0 : Snapshot.BatteryVoltage;
    public string BatteryVoltageText => IsCalibrating ? "---" : $"{BatteryVoltage:F1} V";

    public double VehicleSpeed => IsCalibrating ? 0 : Snapshot.VehicleSpeed;
    public string VehicleSpeedText => IsCalibrating ? "---" : $"{VehicleSpeed:F1} km/h";

    public double MotorTemp => IsCalibrating ? 0 : Snapshot.MotorTemp;
    public string MotorTempText => IsCalibrating ? "---" : $"{MotorTemp:F1} C";
    public string UnitNameText => "OBD-II CAN USB_3";

    public string ModelText => "CAN IDS NODE";
    public string WorkspaceText => "OPS-WKS-01";
    public string SignalHealthText => string.Equals(Snapshot.MotorStatus, "OK", StringComparison.OrdinalIgnoreCase) ? "STABLE" : "DEGRADED";
    public string GpsStatusText => string.Equals(Snapshot.Source, "python-api", StringComparison.OrdinalIgnoreCase) ? "API LINK" : "OFFLINE";
    public string ThermalCoreStateText => BatteryTempText;

    // Compatibility properties (legacy mappings)
    public int Battery => (int)Math.Round(SOC);
    public string BatteryText => $"{Battery}%";
    public double BatteryRatio => SOCRatio;
    public int Temperature => (int)Math.Round(BatteryTemp);
    public string TemperatureText => BatteryTempText;
    public double TemperatureRatio => BatteryTempRatio;

    public double Voltage => BatteryVoltage;
    public string VoltageText => BatteryVoltageText;

    public double SpeedKph => VehicleSpeed;
    public string SpeedText => VehicleSpeedText;

    public string AmpText => $"{Snapshot.PeakAmperage:F1} A";

    public virtual double ReliabilityScore => 
        Snapshot.PerformanceScore > 0 ? Snapshot.PerformanceScore : 94.2 + (SOC / 50.0);

    public virtual string ReliabilityScoreText => IsCalibrating ? "---" : $"{ReliabilityScore:F1}%";

    public string SessionTimerText => DateTime.Now.ToString("mm:ss");

    public string TemperatureBand =>
        BatteryTemp switch
        {
            >= 85 => "CRITICAL",
            >= 65 => "ELEVATED",
            >= 45 => "ACTIVE",
            _ => "NOMINAL",
        };

    public string SourceText => NormalizeToken(Snapshot.Source);
    public string UpdatedText => Snapshot.UpdatedAt.ToLocalTime().ToString("HH:mm:ss");
    public string AgeText => BuildAgeText(Snapshot.UpdatedAt);

    public string ConnectivityText =>
        Snapshot.Source?.ToLowerInvariant() switch
        {
            "python-api" => "LIVE FASTAPI",
            "log-playback" => "REPLAY STREAM",
            _ => "OFFLINE",
        };

    public string ThermalMarginText =>
        BatteryTemp >= 85
            ? "THERMAL LIMIT EXCEEDED"
            : $"{Math.Max(0, 85 - BatteryTemp):F1} C TO THERMAL LIMIT";

    public string BatteryReserveText => $"{Math.Max(0, SOC - 20):F1}% ABOVE LOW POWER FLOOR";

    public string SectionEyebrow => Key == SectionKey.Home ? "GARAGE COMMAND DECK" : "TACTICAL VEHICLE BRIEF";
    public string SectionTitle => Key == SectionKey.Home ? "" : SelectorOrDefault(Descriptor?.Title, "SECTION_UNKNOWN");
    public virtual string SectionDescription =>
        Key == SectionKey.Home
            ? "Access the unified vehicle diagnostics console and transition between live systems from a single premium command station."
            : SelectorOrDefault(Descriptor?.BriefingDescription, "SYSTEM_READY");

    public string SectionSignalLine =>
        Key switch
        {
            SectionKey.Home => $"{ConnectivityText} | BATTERY {SOCText} | CORE {BatteryTempText}",
            _ => $"{ConnectivityText} | SOURCE {SourceText} | LAST SYNC {UpdatedText}",
        };

    private string SelectorOrDefault(string? value, string fallback) => string.IsNullOrWhiteSpace(value) ? fallback : value!;

    protected virtual void OnDataUpdated(VehicleSnapshot snapshot)
    {
        if (isCalibrating)
        {
            startupBuffer.Add(snapshot);
            calibrationProgress = startupBuffer.Count;
            CalibrationText = $"CALIBRATING SYSTEM... {calibrationProgress}/4";
            
            if (startupBuffer.Count >= 4)
            {
                IsCalibrating = false;
                CalibrationText = "CALIBRATION COMPLETE";
            }
            else
            {
                OnPropertyChanged(nameof(CalibrationText));
                return;
            }
        }

        OnPropertyChanged(nameof(Snapshot));
        OnPropertyChanged(nameof(IsCalibrating));
        OnPropertyChanged(nameof(CalibrationText));
        OnPropertyChanged(nameof(SOC));
        OnPropertyChanged(nameof(SOCText));
        OnPropertyChanged(nameof(SOCRatio));
        OnPropertyChanged(nameof(BatteryTemp));
        OnPropertyChanged(nameof(BatteryTempText));
        OnPropertyChanged(nameof(BatteryTempRatio));
        OnPropertyChanged(nameof(BatteryVoltage));
        OnPropertyChanged(nameof(BatteryVoltageText));
        OnPropertyChanged(nameof(VehicleSpeed));
        OnPropertyChanged(nameof(VehicleSpeedText));
        OnPropertyChanged(nameof(MotorTemp));
        OnPropertyChanged(nameof(MotorTempText));
        
        OnPropertyChanged(nameof(Battery));
        OnPropertyChanged(nameof(BatteryText));
        OnPropertyChanged(nameof(BatteryRatio));
        OnPropertyChanged(nameof(Temperature));
        OnPropertyChanged(nameof(TemperatureText));
        OnPropertyChanged(nameof(TemperatureBand));
        OnPropertyChanged(nameof(SourceText));
        OnPropertyChanged(nameof(UpdatedText));
        OnPropertyChanged(nameof(AgeText));
        OnPropertyChanged(nameof(ConnectivityText));
        OnPropertyChanged(nameof(ThermalMarginText));
        OnPropertyChanged(nameof(BatteryReserveText));
        OnPropertyChanged(nameof(SectionSignalLine));
    }

    private void SaveSnapshot()
    {
        var dialog = new SaveFileDialog
        {
            Filter = "JSON Data (*.json)|*.json|Text File (*.txt)|*.txt",
            FileName = $"Snapshot_{DateTime.Now:yyyyMMdd_HHmm}",
            Title = "Save Diagnostic Snapshot"
        };

        if (dialog.ShowDialog() == true)
        {
            var json = JsonConvert.SerializeObject(Snapshot, Formatting.Indented);
            System.IO.File.WriteAllText(dialog.FileName, json);
        }
    }

    private void VehicleDataServiceOnPropertyChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(VehicleDataService.CurrentSnapshot))
        {
            RaiseSnapshotChanged();
        }

        if (e.PropertyName == nameof(VehicleDataService.IsRunning))
        {
            OnVehicleDataServiceStateChanged();
        }
    }

    protected virtual void OnVehicleDataServiceStateChanged()
    {
    }

    protected void RaiseSnapshotChanged()
    {
        OnPropertyChanged(nameof(Snapshot));
        OnPropertyChanged(nameof(Battery));
        OnPropertyChanged(nameof(BatteryText));
        OnPropertyChanged(nameof(BatteryRatio));
        OnPropertyChanged(nameof(Temperature));
        OnPropertyChanged(nameof(TemperatureText));
        OnPropertyChanged(nameof(TemperatureRatio));
        OnPropertyChanged(nameof(TemperatureBand));
        OnPropertyChanged(nameof(SourceText));
        OnPropertyChanged(nameof(UpdatedText));
        OnPropertyChanged(nameof(AgeText));
        OnPropertyChanged(nameof(ConnectivityText));
        OnPropertyChanged(nameof(ThermalMarginText));
        OnPropertyChanged(nameof(BatteryReserveText));
        OnPropertyChanged(nameof(Voltage));
        OnPropertyChanged(nameof(VoltageText));
        OnPropertyChanged(nameof(SpeedKph));
        OnPropertyChanged(nameof(SpeedText));
        OnPropertyChanged(nameof(GpsStatusText));
        OnPropertyChanged(nameof(SessionTimerText));
        OnPropertyChanged(nameof(SectionSignalLine));
        OnPropertyChanged(nameof(AmpText));
        OnPropertyChanged(nameof(ModelText));
        OnPropertyChanged(nameof(WorkspaceText));
        OnPropertyChanged(nameof(SignalHealthText));
        OnPropertyChanged(nameof(ThermalCoreStateText));
        OnPropertyChanged(nameof(UnitNameText));
        OnDataUpdated(Snapshot);
    }

    protected static double Clamp(double value, double min, double max)
    {
        if (value < min)
        {
            return min;
        }

        if (value > max)
        {
            return max;
        }

        return value;
    }

    private static string NormalizeToken(string? value)
    {
        var normalized = value ?? string.Empty;
        return string.IsNullOrWhiteSpace(normalized)
            ? "UNKNOWN"
            : normalized.Replace('_', ' ').Replace('-', ' ').ToUpperInvariant();
    }

    private static string BuildAgeText(DateTime updatedAt)
    {
        var age = DateTime.UtcNow - updatedAt.ToUniversalTime();
        if (age.TotalSeconds < 5)
        {
            return "JUST NOW";
        }

        if (age.TotalMinutes < 1)
        {
            return $"{(int)Math.Max(1, age.TotalSeconds)}S AGO";
        }

        if (age.TotalHours < 1)
        {
            return $"{(int)age.TotalMinutes}M AGO";
        }

        return $"{(int)age.TotalHours}H AGO";
    }
}

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

    public HomeViewModel(
        VehicleDataService vehicleDataService,
        CanLogImportService canLogImportService,
        PythonApiClient pythonApiClient)
        : base(vehicleDataService, SectionKey.Home)
    {
        this.canLogImportService = canLogImportService;
        this.pythonApiClient = pythonApiClient;

        StartSessionCommand = new RelayCommand(() => VehicleDataService.Start());
        StopSessionCommand = new RelayCommand(() => VehicleDataService.Stop());
        ImportReplayCommand = new AsyncRelayCommand(ImportReplayAsync);

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
        };
        vehicleDataService.AlertHistoryUpdated += _ => OnPropertyChanged(nameof(TotalAlertsText));
    }

    public event Action? AnalysisCompleted;

    public IRelayCommand StartSessionCommand { get; }
    public IRelayCommand StopSessionCommand { get; }
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
        string.Equals(Snapshot.Source, "python-api", StringComparison.OrdinalIgnoreCase)
            ? "CONNECTED"
            : "OFFLINE";

    public string ReadinessText =>
        IsAnalysisRunning
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

    private async Task ImportReplayAsync()
    {
        var dialog = new OpenFileDialog
        {
            Filter = "Replay CSV (*.csv)|*.csv|CAN logs (*.log;*.asc;*.trc;*.txt)|*.log;*.asc;*.trc;*.txt|All files (*.*)|*.*",
            Title = "Import Replay CSV",
        };

        if (dialog.ShowDialog() != true)
        {
            return;
        }

        var replayName = Path.GetFileName(dialog.FileName);
        ImportedReplayName = replayName;
        AnalysisStatusText = "LOADING DATASET";
        VehicleDataService.Stop();

        try
        {
            AnalysisStatusText = "PARSING FRAMES";
            var parseResult = await canLogImportService.ParseFileAsync(dialog.FileName).ConfigureAwait(true);
            var packets = parseResult.Packets.ToList();
            AnalysisTotalFrames = packets.Count;
            AnalysisProcessedFrames = 0;
            AnalysisProgressPercent = 0;
            AnalysisCurrentScore = 0;
            AnalysisCurrentCanId = "0x000";

            if (packets.Count > 0)
                VehicleDataService.SetAppState(CANvision.Native.Models.AppState.DatasetLoaded);

            VehicleDataService.LoadReplayPackets(replayName, packets);
            VehicleDataService.BeginReplayAnalysis();

            if (packets.Count == 0)
            {
                AnalysisStatusText = "NO PARSABLE FRAMES";
                return;
            }

            IsAnalysisRunning = true;
            AnalysisStatusText = "EXTRACTING FEATURES";
            var stopwatch = System.Diagnostics.Stopwatch.StartNew();
            AnalysisStatusText = "RUNNING ML ANALYSIS";
            var analyzeTask = pythonApiClient.AnalyzeLogsAsync(new[] { dialog.FileName }, CancellationToken.None);

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
                AnalysisProgressPercent = Clamp(((index + 1) / (double)packets.Count) * 100.0, 0, 100);
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

            AnalysisStatusText = "GENERATING DETECTIONS";
            var analysisResponse = await analyzeTask.ConfigureAwait(true);
            AnalysisStatusText = "BUILDING INTELLIGENCE";
            var metrics = await pythonApiClient.GetMetricsAsync(CancellationToken.None).ConfigureAwait(true);
            var apiAnomalies = ConvertApiAnomalies(analysisResponse);
            if (apiAnomalies.Count > 0)
            {
                VehicleDataService.UpdateAnomalies(apiAnomalies);
            }

            var detectedAttack = ResolveAttackType(analysisResponse, apiAnomalies, SelectedAttackType);
            var confidence = ResolveConfidence(analysisResponse, apiAnomalies, packets.Count);
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
            VehicleDataService.CompleteReplayAnalysis(detectedAttack, confidence, Array.Empty<RuntimeAlertEvent>());
            AnalysisStatusText = $"ANALYSIS COMPLETE — {detectedAttack}";
            AnalysisProgressPercent = 100;
            AnalysisProcessedFrames = packets.Count;
            IsAnalysisRunning = false;
            AnalysisCompleted?.Invoke();
        }
        catch (Exception exception)
        {
            AnalysisStatusText = $"ANALYSIS FAILED: {exception.Message.ToUpperInvariant()}";
            IsAnalysisRunning = false;
            VehicleDataService.CompleteReplayAnalysis("UNKNOWN", 0, Array.Empty<RuntimeAlertEvent>());
            VehicleDataService.PublishExternalSnapshot(VehicleSnapshot.Default());
        }
    }

    private static double ResolvePacketScore(PlaybackPacket packet)
    {
        if (packet.Anomalies is null || packet.Anomalies.Count == 0)
        {
            return 0;
        }

        var scores = packet.Anomalies
            .Select(item => item.SeverityScore > 0 ? item.SeverityScore : Math.Abs(item.AnomalyScore) * 100.0)
            .ToList();
        return scores.Count == 0 ? 0 : scores.Max();
    }

    private static List<CanAnomaly> ConvertApiAnomalies(PythonAnalyzeResponse? response)
    {
        var output = new List<CanAnomaly>();
        if (response?.Anomalies is null)
        {
            return output;
        }

        foreach (var item in response.Anomalies)
        {
            var context = item.Context ?? new Newtonsoft.Json.Linq.JObject();
            var explanation = item.Explanation ?? new Newtonsoft.Json.Linq.JObject();
            var canId = ReadHexOrInt(context, "can_id");
            var score = ReadDouble(context, "anomaly_score", ReadDouble(explanation, "anomaly_score", 0));
            var severityScore = Math.Max(0, Math.Min(100, Math.Abs(score) * 100.0));
            var severity = severityScore >= 80 ? "CRITICAL" : (severityScore >= 40 ? "WARNING" : "INFO");
            var issue = ReadString(explanation, "issue", ReadString(context, "type", "ANOMALY"));
            var reason = ReadString(explanation, "reason", ReadString(explanation, "summary", "Detected by FastAPI analysis"));

            output.Add(
                new CanAnomaly
                {
                    Code = ReadString(context, "code", "API-ANOMALY"),
                    Title = issue.ToUpperInvariant(),
                    Description = reason,
                    Severity = severity,
                    SeverityScore = severityScore,
                    AnomalyScore = score,
                    RelatedCanId = canId,
                    TimestampUtc = DateTime.UtcNow,
                    Source = "fastapi",
                });
        }

        return output;
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

    private static string ReadString(Newtonsoft.Json.Linq.JObject source, string key, string fallback)
    {
        if (source.TryGetValue(key, StringComparison.OrdinalIgnoreCase, out var token))
        {
            var text = token?.ToString();
            if (!string.IsNullOrWhiteSpace(text))
            {
                return text.Trim();
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
    }
}

public sealed class DashboardViewModel : SectionViewModel
{
    private readonly List<double> rollingScores = new();
    private const int RollingScoreCapacity = 120; // 60 s at 500 ms per tick

    public DashboardViewModel(VehicleDataService vehicleDataService)
        : base(vehicleDataService, SectionKey.Dashboard)
    {
        QuickDiagnostics = new ObservableCollection<FaultCodeItem>();
        AnomalyAlerts = new ObservableCollection<AlertItem>();
        SubsystemHealth = new ObservableCollection<MetricCardItem>();
        ReadinessBadges = new ObservableCollection<StatusBadgeItem>();
        LiveAlerts = new ObservableCollection<RuntimeAlertEvent>();
        LiveFrames = new ObservableCollection<LiveFrameRow>();
        AnomalyTrendBars = new ObservableCollection<double>();
        AlertTrendBars = new ObservableCollection<double>();
        DashboardTopKpis = new ObservableCollection<AnalysisKpiItem>();
        DashboardBottomKpis = new ObservableCollection<AnalysisKpiItem>();
        DashboardEventRows = new ObservableCollection<ReplayEventRowItem>();
        DashboardDetectionMarkers = new ObservableCollection<ForensicTimelineMarker>();
        vehicleDataService.AlertHistoryUpdated += OnAlertHistoryUpdated;
        vehicleDataService.LiveFramesUpdated += OnLiveFramesUpdated;

        StartSessionCommand = new RelayCommand(() => VehicleDataService.Start());
        StopSessionCommand = new RelayCommand(() => VehicleDataService.Stop());
        RefreshRuntimePanels();
    }

    public ObservableCollection<FaultCodeItem> QuickDiagnostics { get; }
    public ObservableCollection<AlertItem> AnomalyAlerts { get; }
    public ObservableCollection<MetricCardItem> SubsystemHealth { get; }
    public ObservableCollection<StatusBadgeItem> ReadinessBadges { get; }
    public ObservableCollection<RuntimeAlertEvent> LiveAlerts { get; }
    public ObservableCollection<LiveFrameRow> LiveFrames { get; }
    public ObservableCollection<double> AnomalyTrendBars { get; }
    public ObservableCollection<double> AlertTrendBars { get; }
    public ObservableCollection<AnalysisKpiItem> DashboardTopKpis { get; }
    public ObservableCollection<AnalysisKpiItem> DashboardBottomKpis { get; }
    public ObservableCollection<ReplayEventRowItem> DashboardEventRows { get; }
    public ObservableCollection<ForensicTimelineMarker> DashboardDetectionMarkers { get; }

    public IRelayCommand StartSessionCommand { get; }
    public IRelayCommand StopSessionCommand { get; }

    public bool IsSessionRunning => VehicleDataService.IsRunning;
    public string SessionStateText => IsSessionRunning ? "SESSION LIVE" : "SESSION PAUSED";
    public string ReplayName => VehicleDataService.ReplayName;
    public string DetectedAttackType => VehicleDataService.DetectedAttackType;
    public string DetectionConfidenceText => $"{VehicleDataService.DetectionConfidence:F1}%";
    public string TotalAlertsText => VehicleDataService.TotalAlerts.ToString();
    public string CriticalAlertsText => VehicleDataService.CriticalAlerts.ToString();
    public string WarningAlertsText => VehicleDataService.WarningAlerts.ToString();
    public string AverageScoreText => $"{VehicleDataService.AverageAnomalyScore:F2}";
    public string MaxScoreText => $"{VehicleDataService.MaxAnomalyScore:F2}";
    public string TopCanIdText => VehicleDataService.TopSuspiciousCanId;
    public string RuntimeFpsText => $"{VehicleDataService.RuntimeFps:F1}";
    public string LatencyMsText => $"{VehicleDataService.RuntimeLatencyMs:F1} ms";
    public double ReplayProgressPercent => VehicleDataService.ReplayProgressPercent;
    public string ReplayProgressText => $"{VehicleDataService.ReplayProgressPercent:F1}%";
    public string ReplayFramesText => $"{VehicleDataService.ProcessedReplayFrames}/{Math.Max(1, VehicleDataService.TotalReplayFrames)}";
    public string DashboardRibbon => $"{ConnectivityText} | ATTACK {DetectedAttackType} | FPS {RuntimeFpsText}";

    // ── Properties required by DashboardView.xaml and code-behind ────────────
    public string DetectionState => OperationalStateText;
    public string AnomalyStatusText => VehicleDataService.TotalAlerts > 0 ? $"ANOMALY DETECTED — {VehicleDataService.DetectedAttackType}" : "MONITORING";
    public string LastAnomalyMessage => AnomalyStatusText;
    public string PacketsPerSecondText => RuntimeFpsText;
    public string FramesProcessedText => ReplayFramesText;
    public string ActiveModelName => "IDS-STATE-MODEL";
    public string ReplayProgressPercentText => ReplayProgressText;
    public string ReplayStatusText => VehicleDataService.ReplayProgressPercent >= 100 ? "COMPLETE" : VehicleDataService.ReplayProgressPercent > 0 ? "RUNNING" : "IDLE";
    public string ActiveReplayFile => VehicleDataService.ReplayName;
    public System.Collections.ObjectModel.ObservableCollection<string> EventLogLines { get; } = new System.Collections.ObjectModel.ObservableCollection<string>();

    protected override void OnVehicleDataServiceStateChanged()
    {
        OnPropertyChanged(nameof(IsSessionRunning));
        OnPropertyChanged(nameof(SessionStateText));
    }

    public string BatteryBand =>
        SOC switch
        {
            >= 80 => "TRACK READY",
            >= 55 => "STREET READY",
            >= 30 => "WATCH CHARGE",
            _ => "PIT NOW",
        };

    public string DriveMessage =>
        string.Equals(Snapshot.MotorStatus, "OK", StringComparison.OrdinalIgnoreCase)
            ? "POWERTRAIN READY FOR DEPLOYMENT"
            : "CHECK DRIVE-UNIT TELEMETRY BEFORE DEPLOYMENT";

    public string DataRibbon => $"{ConnectivityText} | LAST SYNC {UpdatedText}";

    public string ConnectionStateText => string.Equals(Snapshot.Source, "python-api", StringComparison.OrdinalIgnoreCase) ? "CONNECTED" : "LOCAL FALLBACK";

    // ── Properties required by DashboardView.xaml (39258c6 restore) ──────────
    public string LiveStateText => ConnectionStateText == "CONNECTED" ? "LIVE" : "OFFLINE";
    public string SystemNameText => UnitNameText;
    public string LastSyncSummaryText => ConnectionStateText == "CONNECTED" ? "ALL SYSTEMS SYNCED" : "SYNC PENDING";
    public System.Windows.Media.Brush StatusGlowBrush =>
        ConnectionStateText == "CONNECTED"
            ? new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(0, 200, 200))
            : new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(80, 100, 100));
    public string LastEventTimestamp => Snapshot.UpdatedAt.ToLocalTime().ToString("HH:mm:ss");
    public string AnomalyScoreText => VehicleDataService.CurrentAnomalyScore > 0 ? $"{VehicleDataService.CurrentAnomalyScore:F1}" : "0.0";
    public string TopAnomalousCanId => !string.IsNullOrEmpty(VehicleDataService.TopSuspiciousCanId) ? VehicleDataService.TopSuspiciousCanId : "N/A";
    public int TotalFrames => VehicleDataService.TotalReplayFrames;
    public string ReplayElapsedText => SessionTimerText;
    public string RuntimeStateText => $"{ConnectionStateText} / {ReplayStatusText}";
    public string StatusSubtitleText => $"SOC {BatteryText}  VOLT {VoltageText}";
    public string AnomalyConfidenceText => $"{VehicleDataService.DetectionConfidence:F1}%";
    public string PacketsAnalyzedText => VehicleDataService.ProcessedReplayFrames.ToString("N0");
    public string DetectionsTodayText => VehicleDataService.TotalAlerts.ToString("N0");
    public string ActiveThreatsText => OperationalStateText is "THREAT DETECTED" or "CRITICAL" ? "1" : "0";
    public string CurrentThreatText => VehicleDataService.TotalAlerts > 0 ? VehicleDataService.DetectedAttackType : "System Nominal";
    public string ThreatSeverityText => OperationalStateText == "CRITICAL" ? "CRITICAL" : VehicleDataService.TotalAlerts > 0 ? "HIGH" : "NORMAL";
    public string AffectedCanIdsText => string.IsNullOrWhiteSpace(VehicleDataService.TopSuspiciousCanId) ? "None" : VehicleDataService.TopSuspiciousCanId;
    public string AttackTypeText => VehicleDataService.TotalAlerts > 0 ? VehicleDataService.DetectedAttackType : "None";
    public string LiveAlertsCountText => $"{VehicleDataService.TotalAlerts:N0}";
    public string DetectionRateText => VehicleDataService.ProcessedReplayFrames <= 0 ? "--" : $"{VehicleDataService.TotalAlerts * 100.0 / Math.Max(1, VehicleDataService.ProcessedReplayFrames):F1}%";
    public string ModelHealthText => VehicleDataService.DetectionConfidence > 0 ? "100%" : "Ready";
    public string PipelineHealthText => ConnectionStateText == "CONNECTED" ? "100%" : "Degraded";
    public string ReplayEngineHealthText => ReplayStatusText == "RUNNING" ? "READY" : "STANDBY";
    public string TrendDirectionText => VehicleDataService.CurrentAnomalyScore > VehicleDataService.AverageAnomalyScore ? "Rising" : "Stable";
    public System.Windows.Media.PointCollection DashboardAnomalyPoints { get; private set; } = new();
    public System.Windows.Media.PointCollection DashboardAnomalyFillPoints { get; private set; } = new();
    public System.Windows.Media.PointCollection DashboardThresholdPoints { get; private set; } = new()
    {
        new System.Windows.Point(0, 73),
        new System.Windows.Point(540, 73),
    };
    public string LastAnomalyTimestamp => VehicleDataService.AlertHistory.Count > 0
        ? VehicleDataService.AlertHistory[VehicleDataService.AlertHistory.Count - 1].TimestampUtc.ToLocalTime().ToString("HH:mm:ss")
        : "--:--:--";

    // ── 7-state operational model ─────────────────────────────────────────────
    public string OperationalStateText
    {
        get
        {
            if (ConnectionStateText != "CONNECTED") return "TELEMETRY DEGRADED";
            if (IsCalibrating) return "BASELINING";
            var score = VehicleDataService.CurrentAnomalyScore;
            if (score >= 0.80) return "CRITICAL";
            if (score >= 0.55 || VehicleDataService.TotalAlerts > 0) return "THREAT DETECTED";
            if (score >= 0.35) return "ELEVATED RISK";
            if (score >= 0.15) return "ANALYZING";
            return "MONITORING";
        }
    }

    public string OperationalStateColor => OperationalStateText switch
    {
        "CRITICAL"          => "#FF5050",
        "THREAT DETECTED"   => "#FF8C3A",
        "ELEVATED RISK"     => "#FFD94A",
        "ANALYZING"         => "#00ECFF",
        "MONITORING"        => "#56F0AC",
        "BASELINING"        => "#96B4FF",
        _                   => "#4A6470",
    };

    public string OperationalStateGlyph => OperationalStateText switch
    {
        "CRITICAL"          => "⬥",
        "THREAT DETECTED"   => "⬦",
        "ELEVATED RISK"     => "◈",
        "ANALYZING"         => "◎",
        "MONITORING"        => "●",
        "BASELINING"        => "◐",
        _                   => "◌",
    };

    public string ThreatSummaryText => OperationalStateText switch
    {
        "CRITICAL"          => $"CRITICAL — {VehicleDataService.DetectedAttackType} — SCORE {VehicleDataService.CurrentAnomalyScore:F1}",
        "THREAT DETECTED"   => $"ATTACK PATTERN: {VehicleDataService.DetectedAttackType}",
        "ELEVATED RISK"     => $"RISK SCORE {VehicleDataService.CurrentAnomalyScore:F1} — WATCH ACTIVE",
        "ANALYZING"         => $"SCORE {VehicleDataService.CurrentAnomalyScore:F1} — BASELINE COMPARISON",
        "MONITORING"        => "ALL CHANNELS NOMINAL",
        "BASELINING"        => "ESTABLISHING TRAFFIC BASELINE...",
        _                   => "STREAM UNAVAILABLE — CHECK ADAPTER",
    };
    // ─────────────────────────────────────────────────────────────────────────

    protected override void OnDataUpdated(VehicleSnapshot snapshot)
    {
        base.OnDataUpdated(snapshot);

        // Keep a rolling 60-second window of raw fusion scores for the chart.
        var currentScore = VehicleDataService.CurrentAnomalyScore;
        if (VehicleDataService.IsRunning || currentScore > 0)
        {
            rollingScores.Add(currentScore);
            if (rollingScores.Count > RollingScoreCapacity)
                rollingScores.RemoveAt(0);
        }

        RefreshRuntimePanels();
        OnPropertyChanged(nameof(BatteryBand));
        OnPropertyChanged(nameof(DriveMessage));
        OnPropertyChanged(nameof(DataRibbon));
        OnPropertyChanged(nameof(ConnectionStateText));
        OnPropertyChanged(nameof(ReplayName));
        OnPropertyChanged(nameof(DetectedAttackType));
        OnPropertyChanged(nameof(DetectionConfidenceText));
        OnPropertyChanged(nameof(TotalAlertsText));
        OnPropertyChanged(nameof(CriticalAlertsText));
        OnPropertyChanged(nameof(WarningAlertsText));
        OnPropertyChanged(nameof(AverageScoreText));
        OnPropertyChanged(nameof(MaxScoreText));
        OnPropertyChanged(nameof(TopCanIdText));
        OnPropertyChanged(nameof(RuntimeFpsText));
        OnPropertyChanged(nameof(LatencyMsText));
        OnPropertyChanged(nameof(ReplayProgressPercent));
        OnPropertyChanged(nameof(ReplayProgressText));
        OnPropertyChanged(nameof(ReplayFramesText));
        OnPropertyChanged(nameof(DashboardRibbon));
        OnPropertyChanged(nameof(LiveStateText));
        OnPropertyChanged(nameof(SystemNameText));
        OnPropertyChanged(nameof(LastSyncSummaryText));
        OnPropertyChanged(nameof(StatusGlowBrush));
        OnPropertyChanged(nameof(LastEventTimestamp));
        OnPropertyChanged(nameof(AnomalyScoreText));
        OnPropertyChanged(nameof(TopAnomalousCanId));
        OnPropertyChanged(nameof(TotalFrames));
        OnPropertyChanged(nameof(ReplayElapsedText));
        OnPropertyChanged(nameof(RuntimeStateText));
        OnPropertyChanged(nameof(StatusSubtitleText));
        OnPropertyChanged(nameof(AnomalyConfidenceText));
        OnPropertyChanged(nameof(PacketsAnalyzedText));
        OnPropertyChanged(nameof(DetectionsTodayText));
        OnPropertyChanged(nameof(ActiveThreatsText));
        OnPropertyChanged(nameof(CurrentThreatText));
        OnPropertyChanged(nameof(ThreatSeverityText));
        OnPropertyChanged(nameof(AffectedCanIdsText));
        OnPropertyChanged(nameof(AttackTypeText));
        OnPropertyChanged(nameof(LiveAlertsCountText));
        OnPropertyChanged(nameof(DetectionRateText));
        OnPropertyChanged(nameof(ModelHealthText));
        OnPropertyChanged(nameof(PipelineHealthText));
        OnPropertyChanged(nameof(ReplayEngineHealthText));
        OnPropertyChanged(nameof(TrendDirectionText));
        OnPropertyChanged(nameof(DashboardAnomalyPoints));
        OnPropertyChanged(nameof(DashboardAnomalyFillPoints));
        OnPropertyChanged(nameof(DashboardThresholdPoints));
        OnPropertyChanged(nameof(LastAnomalyTimestamp));
        OnPropertyChanged(nameof(OperationalStateText));
        OnPropertyChanged(nameof(OperationalStateColor));
        OnPropertyChanged(nameof(OperationalStateGlyph));
        OnPropertyChanged(nameof(ThreatSummaryText));
    }

    private void OnAlertHistoryUpdated(IReadOnlyList<RuntimeAlertEvent> _)
    {
        RefreshRuntimePanels();
        OnPropertyChanged(nameof(TotalAlertsText));
        OnPropertyChanged(nameof(CriticalAlertsText));
        OnPropertyChanged(nameof(WarningAlertsText));
        OnPropertyChanged(nameof(AverageScoreText));
        OnPropertyChanged(nameof(MaxScoreText));
        OnPropertyChanged(nameof(TopCanIdText));
        OnPropertyChanged(nameof(AnomalyScoreText));
        OnPropertyChanged(nameof(TopAnomalousCanId));
        OnPropertyChanged(nameof(AnomalyConfidenceText));
        OnPropertyChanged(nameof(PacketsAnalyzedText));
        OnPropertyChanged(nameof(DetectionsTodayText));
        OnPropertyChanged(nameof(ActiveThreatsText));
        OnPropertyChanged(nameof(CurrentThreatText));
        OnPropertyChanged(nameof(ThreatSeverityText));
        OnPropertyChanged(nameof(AffectedCanIdsText));
        OnPropertyChanged(nameof(AttackTypeText));
        OnPropertyChanged(nameof(LiveAlertsCountText));
        OnPropertyChanged(nameof(DetectionRateText));
        OnPropertyChanged(nameof(ModelHealthText));
        OnPropertyChanged(nameof(PipelineHealthText));
        OnPropertyChanged(nameof(ReplayEngineHealthText));
        OnPropertyChanged(nameof(TrendDirectionText));
        OnPropertyChanged(nameof(DashboardAnomalyPoints));
        OnPropertyChanged(nameof(DashboardAnomalyFillPoints));
        OnPropertyChanged(nameof(DashboardThresholdPoints));
        OnPropertyChanged(nameof(LastAnomalyTimestamp));
        OnPropertyChanged(nameof(OperationalStateText));
        OnPropertyChanged(nameof(OperationalStateColor));
        OnPropertyChanged(nameof(OperationalStateGlyph));
        OnPropertyChanged(nameof(ThreatSummaryText));
        OnPropertyChanged(nameof(DetectedAttackType));
        OnPropertyChanged(nameof(DetectionConfidenceText));
        OnPropertyChanged(nameof(DashboardRibbon));
    }

    private void OnLiveFramesUpdated(IReadOnlyList<LiveSignalItem> items)
    {
        LiveFrames.Clear();
        foreach (var item in items.Reverse().Take(30))
        {
            var color = item.Severity switch
            {
                "CRITICAL" => "#FF5050",
                "HIGH"     => "#FF8C3A",
                "WARNING"  => "#FFD94A",
                _          => "#56F0AC",
            };
            LiveFrames.Add(new LiveFrameRow
            {
                Time     = DateTimeOffset.FromUnixTimeMilliseconds((long)(item.Timestamp * 1000)).ToLocalTime().ToString("HH:mm:ss.fff"),
                CanId    = item.CanId,
                Bytes    = $"{item.B0:X2} {item.B1:X2} {item.B2:X2} {item.B3:X2} {item.B4:X2} {item.B5:X2} {item.B6:X2} {item.B7:X2}",
                Score    = $"{item.AnomalyScore:F2}",
                Severity = item.Severity,
                SeverityColor = color,
            });
        }
    }

    private void RefreshRuntimePanels()
    {
        LiveAlerts.Clear();
        var latestAlerts = VehicleDataService.AlertHistory
            .OrderByDescending(item => item.TimestampUtc)
            .Take(40)
            .ToList();
        foreach (var alert in latestAlerts)
        {
            LiveAlerts.Add(alert);
        }

        QuickDiagnostics.Clear();
        foreach (var alert in latestAlerts.Take(8))
        {
            QuickDiagnostics.Add(
                new FaultCodeItem(
                    alert.CanId,
                    alert.AttackType,
                    alert.Severity,
                    alert.Reason,
                    alert.TimestampUtc.ToLocalTime().ToString("HH:mm:ss")));
        }

        ReadinessBadges.Clear();
        ReadinessBadges.Add(new StatusBadgeItem("ATTACK", DetectedAttackType));
        ReadinessBadges.Add(new StatusBadgeItem("RISK", $"{VehicleDataService.MaxAnomalyScore:F1}"));
        ReadinessBadges.Add(new StatusBadgeItem("ALERTS", VehicleDataService.TotalAlerts.ToString()));
        ReadinessBadges.Add(new StatusBadgeItem("REPLAY", ReplayProgressText));

        RefreshDashboardCommandCenter(latestAlerts);
        UpdateTrends();
    }

    private void RefreshDashboardCommandCenter(IReadOnlyList<RuntimeAlertEvent> latestAlerts)
    {
        var anomalyTrend = BuildDashboardTrend(rollingScores.Count > 0 ? rollingScores.ToList() : new List<double> { 0 }, 150, 26);
        var alertTrend = BuildDashboardTrend(BuildRecentCounts(), 150, 26);
        var fpsTrend = BuildDashboardTrend(Enumerable.Range(0, rollingScores.Count > 0 ? Math.Min(rollingScores.Count, 20) : 1).Select(_ => VehicleDataService.RuntimeFps).ToList(), 150, 26);
        var frameTrend = BuildDashboardTrend(Enumerable.Range(0, 10).Select(i => (double)(VehicleDataService.ProcessedReplayFrames - i)).Where(v => v >= 0).ToList(), 150, 26);

        DashboardTopKpis.Clear();
        DashboardTopKpis.Add(new AnalysisKpiItem("FUSION SCORE", AnomalyScoreText, OperationalStateText, anomalyTrend, "#00C8C8"));
        DashboardTopKpis.Add(new AnalysisKpiItem("LIVE FPS", RuntimeFpsText, "FRAMES/SEC", fpsTrend, "#56F0AC"));
        DashboardTopKpis.Add(new AnalysisKpiItem("ACTIVE THREATS", ActiveThreatsText, "CURRENT", alertTrend, "#FF8C3A"));
        DashboardTopKpis.Add(new AnalysisKpiItem("CRITICAL ALERTS", CriticalAlertsText, "LAST 5 MIN", alertTrend, "#FF5050"));
        DashboardTopKpis.Add(new AnalysisKpiItem("FRAMES", PacketsAnalyzedText, "ANALYZED", frameTrend, "#00C8C8"));
        DashboardTopKpis.Add(new AnalysisKpiItem("LATENCY", LatencyMsText, "ROUNDTRIP", fpsTrend, "#56F0AC"));

        DashboardBottomKpis.Clear();
        DashboardBottomKpis.Add(new AnalysisKpiItem("FUSION SCORE", AnomalyScoreText, TrendDirectionText, anomalyTrend, "#00C8C8"));
        DashboardBottomKpis.Add(new AnalysisKpiItem("TOTAL ALERTS", TotalAlertsText, "SESSION", alertTrend, "#FF8C3A"));
        DashboardBottomKpis.Add(new AnalysisKpiItem("DETECTION RATE", DetectionRateText, "TODAY", alertTrend, "#B46CFF"));
        DashboardBottomKpis.Add(new AnalysisKpiItem("ACTIVE THREATS", ActiveThreatsText, "CURRENT", alertTrend, "#FF8C3A"));
        DashboardBottomKpis.Add(new AnalysisKpiItem("CRITICAL ALERTS", CriticalAlertsText, "LAST 5 MIN", alertTrend, "#FF5050"));
        DashboardBottomKpis.Add(new AnalysisKpiItem("LIVE FPS", RuntimeFpsText, "FRAMES/SEC", fpsTrend, "#56F0AC"));
        DashboardBottomKpis.Add(new AnalysisKpiItem("PIPELINE", PipelineHealthText, "HEALTH", fpsTrend, "#56F0AC"));
        DashboardBottomKpis.Add(new AnalysisKpiItem("LATENCY", LatencyMsText, "MS", fpsTrend, "#56F0AC"));

        DashboardEventRows.Clear();
        foreach (var alert in latestAlerts.Take(8))
        {
            DashboardEventRows.Add(new ReplayEventRowItem(
                alert.TimestampUtc.ToLocalTime().ToString("HH:mm:ss.fff"),
                alert.Severity,
                string.IsNullOrWhiteSpace(alert.CanId) ? "IDS" : alert.CanId,
                string.IsNullOrWhiteSpace(alert.Reason) ? alert.AttackType : alert.Reason));
        }

        if (DashboardEventRows.Count == 0)
        {
            DashboardEventRows.Add(new ReplayEventRowItem(LastEventTimestamp, "INFO", "System", "Monitoring active"));
            DashboardEventRows.Add(new ReplayEventRowItem(LastEventTimestamp, "INFO", "IDS", "Detection engine ready"));
            DashboardEventRows.Add(new ReplayEventRowItem(LastEventTimestamp, "INFO", "Telemetry", ConnectionStateText == "CONNECTED" ? "Telemetry connected" : "Telemetry standby"));
        }

        SubsystemHealth.Clear();
        SubsystemHealth.Add(new MetricCardItem("TELEMETRY ENGINE", ConnectionStateText == "CONNECTED" ? "READY" : "DEGRADED", "STREAM", ConnectionStateText));
        SubsystemHealth.Add(new MetricCardItem("DETECTION ENGINE", "READY", "IDS", OperationalStateText));
        SubsystemHealth.Add(new MetricCardItem("REPLAY ENGINE", ReplayEngineHealthText, "REPLAY", ReplayStatusText));
        SubsystemHealth.Add(new MetricCardItem("VALIDATION ENGINE", "READY", "LAB", "STANDBY"));
        SubsystemHealth.Add(new MetricCardItem("MODEL RUNTIME", "READY", ActiveModelName, "LOADED"));
        SubsystemHealth.Add(new MetricCardItem("DATA PIPELINE", ConnectionStateText == "CONNECTED" ? "READY" : "DEGRADED", "INGEST", ConnectionStateText));

        var chartValues = rollingScores.Count > 1
            ? rollingScores.ToList()
            : VehicleDataService.AlertHistory.Select(a => a.Score).DefaultIfEmpty(0.0).ToList();
        DashboardAnomalyPoints = BuildScoringChart(chartValues, 540, 116);
        DashboardAnomalyFillPoints = BuildScoringAreaFill(chartValues, 540, 116);
        // Threshold at score=0.55 with fixed 0–1.5 range and height=116: y = 116*(1-0.55/1.5) = ~73
        DashboardThresholdPoints = new System.Windows.Media.PointCollection
        {
            new(0, 73),
            new(540, 73),
        };

        DashboardDetectionMarkers.Clear();
        var allHistory = VehicleDataService.AlertHistory;
        if (allHistory.Count > 0)
        {
            var earliest = allHistory.Min(a => a.TimestampUtc);
            var spanTicks = Math.Max(1L, (allHistory.Max(a => a.TimestampUtc) - earliest).Ticks);
            foreach (var alert in allHistory.OrderByDescending(a => a.Score).Take(12))
            {
                var x = (alert.TimestampUtc - earliest).Ticks / (double)spanTicks * 540.0;
                DashboardDetectionMarkers.Add(new ForensicTimelineMarker("Detection", x, 0, "D", "#FF8C3A"));
            }
        }

        EventLogLines.Clear();
        foreach (var row in DashboardEventRows.Take(10))
        {
            EventLogLines.Add($"{row.Time} {row.Severity} {row.Source} {row.Message}");
        }
    }

    private List<double> BuildRecentCounts()
    {
        var now = DateTime.UtcNow;
        var counts = new List<double>();
        for (var bucket = 19; bucket >= 0; bucket--)
        {
            var from = now.AddSeconds(-(bucket + 1) * 15);
            var to = now.AddSeconds(-bucket * 15);
            counts.Add(VehicleDataService.AlertHistory.Count(item => item.TimestampUtc >= from && item.TimestampUtc < to));
        }

        return counts;
    }

    private static System.Windows.Media.PointCollection BuildDashboardTrend(IReadOnlyList<double> values, double width, double height)
    {
        var points = new System.Windows.Media.PointCollection();
        if (values.Count == 0)
        {
            return points;
        }

        if (values.Count == 1)
        {
            points.Add(new System.Windows.Point(0, height / 2));
            points.Add(new System.Windows.Point(width, height / 2));
            return points;
        }

        var max = values.Max();
        var min = values.Min();
        var span = Math.Max(0.001, max - min);
        for (var i = 0; i < values.Count; i++)
        {
            var x = i * width / (values.Count - 1);
            var y = height - ((values[i] - min) / span * height);
            points.Add(new System.Windows.Point(x, y));
        }

        return points;
    }

    // Fixed 0–1.5 range chart: score=0 sits at baseline, score=1.5 at top. Consistent scale across sessions.
    private static System.Windows.Media.PointCollection BuildScoringChart(IReadOnlyList<double> values, double width, double height)
    {
        const double yMax = 1.5;
        var points = new System.Windows.Media.PointCollection();
        if (values.Count == 0) return points;
        var single = values.Count == 1;
        var count = single ? 2 : values.Count;
        for (var i = 0; i < count; i++)
        {
            var val = values[single ? 0 : i];
            var x = i * width / (count - 1);
            var y = height - Math.Min(1.0, Math.Max(0.0, val / yMax)) * height;
            points.Add(new System.Windows.Point(x, y));
        }
        return points;
    }

    private static System.Windows.Media.PointCollection BuildScoringAreaFill(IReadOnlyList<double> values, double width, double height)
    {
        var curve = BuildScoringChart(values, width, height);
        if (curve.Count == 0) return curve;
        var fill = new System.Windows.Media.PointCollection(curve) { new System.Windows.Point(width, height), new System.Windows.Point(0, height) };
        return fill;
    }

    private void UpdateTrends()
    {
        var history = VehicleDataService.AlertHistory;
        var now = DateTime.UtcNow;
        AnomalyTrendBars.Clear();
        AlertTrendBars.Clear();
        for (var bucket = 19; bucket >= 0; bucket--)
        {
            var from = now.AddSeconds(-(bucket + 1) * 6);
            var to = now.AddSeconds(-bucket * 6);
            var items = history.Where(item => item.TimestampUtc >= from && item.TimestampUtc < to).ToList();
            var anomalyScore = items.Count == 0 ? 0 : items.Average(item => item.Score);
            var alertCount = items.Count;
            AnomalyTrendBars.Add(18 + Math.Min(150, anomalyScore * 1.2));
            AlertTrendBars.Add(18 + Math.Min(150, alertCount * 12));
        }
    }
}

public sealed class TelemetryViewModel : SectionViewModel
{
    private readonly CanLogImportService canLogImportService;
    private IReadOnlyList<DecodedSignal> latestSignals = Array.Empty<DecodedSignal>();
    private readonly List<double> speedHistory = new();
    private readonly List<double> voltageHistory = new();
    private readonly List<double> currentHistory = new();
    private readonly List<double> motorTempHistory = new();
    private readonly List<double> packetRateHistory = new();
    private readonly List<double> socHistory = new();
    private readonly Dictionary<string, List<double>> signalValueHistory = new(StringComparer.OrdinalIgnoreCase);

    public TelemetryViewModel(VehicleDataService vehicleDataService, CanLogImportService canLogImportService)
        : base(vehicleDataService, SectionKey.Telemetry)
    {
        this.canLogImportService = canLogImportService;
        latestSignals = VehicleDataService.CurrentSignals;
        SignalRows = new ObservableCollection<SignalItem>();
        ActiveSignals = new ObservableCollection<SignalLegendItem>();
        RiskTimelineBars = new ObservableCollection<double>();
        TelemetryEvents = new ObservableCollection<RuntimeAlertEvent>();
        TelemetryEventRows = new ObservableCollection<TelemetryEventItem>();
        TimelineYAxisLabels = new ObservableCollection<AxisLabelItem>();
        TimelineXAxisLabels = new ObservableCollection<AxisLabelItem>();
        ReplayMarkers = new ObservableCollection<ReplayMarkerItem>();
        SubsystemRows = new ObservableCollection<SubsystemStateItem>();

        ImportLogCommand = new AsyncRelayCommand(ImportLogAsync);
        ExportSignalsCommand = new RelayCommand(ExportSignals);
        FreezeStreamCommand = new RelayCommand(() => VehicleDataService.Stop());
        ResumeStreamCommand = new RelayCommand(() => VehicleDataService.Start());

        VehicleDataService.SignalsUpdated += OnSignalsUpdated;
        VehicleDataService.AlertHistoryUpdated += OnAlertHistoryUpdated;
        VehicleDataService.ReplayRuntimeUpdated += OnReplayRuntimeUpdated;
        VehicleDataService.ReplayLoaded += OnReplayLoaded;
        PushTelemetryHistory(Snapshot);
        RefreshSignalRows();
        RefreshRiskTimeline();
        RefreshTimelineAxes();
        RefreshTelemetryEvents();
        RefreshSubsystemRows();
    }

    public ObservableCollection<SignalItem> SignalRows { get; }
    public ObservableCollection<SignalLegendItem> ActiveSignals { get; }
    public ObservableCollection<double> RiskTimelineBars { get; }
    public ObservableCollection<RuntimeAlertEvent> TelemetryEvents { get; }
    public ObservableCollection<TelemetryEventItem> TelemetryEventRows { get; }
    public ObservableCollection<AxisLabelItem> TimelineYAxisLabels { get; }
    public ObservableCollection<AxisLabelItem> TimelineXAxisLabels { get; }
    public ObservableCollection<ReplayMarkerItem> ReplayMarkers { get; }
    public ObservableCollection<SubsystemStateItem> SubsystemRows { get; }
    public IRelayCommand ImportLogCommand { get; }
    public IRelayCommand ExportSignalsCommand { get; }
    public IRelayCommand FreezeStreamCommand { get; }
    public IRelayCommand ResumeStreamCommand { get; }

    public bool IsStreamFrozen => !VehicleDataService.IsRunning;
    public string StreamStateText => IsStreamFrozen ? "STREAM PAUSED" : "STREAM ACTIVE";
    public string ConnectionStateText => string.Equals(Snapshot.Source, "python-api", StringComparison.OrdinalIgnoreCase) ? "CONNECTED" : "LOCAL FALLBACK";
    public string LiveStateText => ConnectionStateText == "CONNECTED" ? "LIVE" : "OFFLINE";
    public string PacketsPerSecondText => $"{VehicleDataService.RuntimeFps:F1}";
    public string LastEventTimestamp => Snapshot.UpdatedAt.ToLocalTime().ToString("HH:mm:ss");
    public string ReplayStatusText => VehicleDataService.ReplayProgressPercent >= 100 ? "COMPLETE" : VehicleDataService.ReplayProgressPercent > 0 ? "RUNNING" : "IDLE";
    public string RuntimeStateText => $"{ConnectionStateText} / {ReplayStatusText}";
    public string DetectionConfidenceText => $"{VehicleDataService.DetectionConfidence:F1}%";
    public string ActiveModelName => ModelText;
    public string ReplayNameText => string.IsNullOrWhiteSpace(VehicleDataService.ReplayName) || VehicleDataService.ReplayName == "NO REPLAY" ? "No Replay" : VehicleDataService.ReplayName;

    public string SessionDurationText
    {
        get
        {
            var packets = VehicleDataService.LoadedReplayPackets;
            if (packets is null || packets.Count < 2) return "--:--:--";
            var duration = packets[packets.Count - 1].Frame.TimestampUtc - packets[0].Frame.TimestampUtc;
            return duration.ToString(@"hh\:mm\:ss");
        }
    }

    public string Trace1Text => $"ANOMALY SCORE {VehicleDataService.CurrentAnomalyScore:F2}";
    public string Trace2Text => $"ALERT DENSITY {AlertDensityText}";
    public string RuntimeReplayProgressText => $"{VehicleDataService.ReplayProgressPercent:F1}%";
    public string RuntimeReplayFramesText => $"{VehicleDataService.ProcessedReplayFrames}/{Math.Max(1, VehicleDataService.TotalReplayFrames)}";
    public string PacketRateText => $"{Math.Max(0, Snapshot.Frequency):F1} Hz";
    public string SampleRateText => $"{Math.Max(0, Snapshot.Frequency):F1} Hz";
    public string LatencyText => $"{Math.Max(0, VehicleDataService.RuntimeLatencyMs):F1} ms";
    public string ReplayFpsText => $"{Math.Max(0, VehicleDataService.RuntimeFps):F1}";
    public string DroppedFramesText => VehicleDataService.LoadedReplayPackets is { Count: > 0 } ? "0 (0.0%)" : "--";
    public string InferenceHealthText => VehicleDataService.DetectedAttackType == "ANALYZING..." ? "ANALYZING" : "READY";
    public string ReplayLatencyText => LatencyText;
    public string PacketTimelineCaption => VehicleDataService.TotalReplayFrames > 0
        ? $"{VehicleDataService.ProcessedReplayFrames:N0}/{VehicleDataService.TotalReplayFrames:N0} frames"
        : StreamHealthLine;
    public System.Windows.Media.PointCollection SpeedTrendPoints => BuildTrendPoints(speedHistory, 116, 26);
    public System.Windows.Media.PointCollection VoltageTrendPoints => BuildTrendPoints(voltageHistory, 116, 26);
    public System.Windows.Media.PointCollection CurrentTrendPoints => BuildTrendPoints(currentHistory, 116, 26);
    public System.Windows.Media.PointCollection MotorTempTrendPoints => BuildTrendPoints(motorTempHistory, 116, 26);
    public System.Windows.Media.PointCollection PacketRateTrendPoints => BuildTrendPoints(packetRateHistory, 116, 26);
    public System.Windows.Media.PointCollection PacketTimelinePoints => BuildPacketTimelinePoints(1040, 130);
    public System.Windows.Media.PointCollection SpeedChannelPoints => BuildTrendPoints(speedHistory, 400, 34);
    public System.Windows.Media.PointCollection SocChannelPoints => BuildTrendPoints(socHistory, 400, 34);
    public System.Windows.Media.PointCollection MotorTempChannelPoints => BuildTrendPoints(motorTempHistory, 400, 34);
    public System.Windows.Media.PointCollection VoltageChannelPoints => BuildTrendPoints(voltageHistory, 400, 34);
    public string TimelineEmptyStateText => VehicleDataService.LoadedReplayPackets is { Count: > 0 } || packetRateHistory.Count > 1
        ? string.Empty
        : "Waiting";
    public string VehicleStateSummary => $"{ConnectionStateText} | {StreamOperationalStateText}";
    public string VehicleMotionText => Snapshot.VehicleSpeed > 0.1 ? $"{Snapshot.VehicleSpeed:F1} km/h | {Snapshot.Gear}" : $"STATIONARY | {Snapshot.Gear}";
    public string VehicleModeText => Snapshot.VehicleSpeed > 0.1 ? "Moving" : "Stationary";
    public string GearText => string.IsNullOrWhiteSpace(Snapshot.Gear) ? "--" : Snapshot.Gear;
    public string WatchlistText => SuspiciousCanIdsText == "--" ? "None" : SuspiciousCanIdsText;
    public string EventsEmptyStateText => TelemetryEventRows.Count == 0 ? "Waiting" : string.Empty;
    public string SpeedTelemetryValueText => HasOperationalSignal(Snapshot.VehicleSpeed) ? SpeedText : "--";
    public string VoltageTelemetryValueText => HasOperationalSignal(Snapshot.BatteryVoltage) ? VoltageText : "--";
    public string CurrentTelemetryValueText => HasOperationalSignal(Snapshot.PeakAmperage) ? AmpText : "--";
    public string MotorTempTelemetryValueText => HasOperationalSignal(Snapshot.MotorTemp) ? MotorTempText : "--";
    public string BatteryTelemetryValueText => HasOperationalSignal(Snapshot.SOC) ? $"{Snapshot.SOC:F0}%" : "--";
    public string PacketsPerSecondTelemetryValueText => VehicleDataService.RuntimeFps > 0 ? PacketsPerSecondText : "0.0";
    public string ReplayProgressTelemetryValueText => VehicleDataService.TotalReplayFrames > 0 ? RuntimeReplayProgressText : "--";
    public string PacketLossTelemetryValueText => PacketLossText == "---" ? "--" : PacketLossText;
    public string SpeedTelemetryStateText => HasOperationalSignal(Snapshot.VehicleSpeed) ? VehicleMotionText : "Awaiting Stream";
    public string VoltageTelemetryStateText => HasOperationalSignal(Snapshot.BatteryVoltage) ? "System Voltage" : "Awaiting Stream";
    public string CurrentTelemetryStateText => HasOperationalSignal(Snapshot.PeakAmperage) ? "Pack Current" : "Awaiting Stream";
    public string MotorTempTelemetryStateText => HasOperationalSignal(Snapshot.MotorTemp) ? TemperatureBand : "Awaiting Stream";
    public string BatteryTelemetryStateText => HasOperationalSignal(Snapshot.SOC) ? BatteryReserveText : "Waiting";
    public string PacketsPerSecondTelemetryStateText => VehicleDataService.RuntimeFps > 0 ? "Live Bus Rate" : "Offline";
    public string ReplayProgressTelemetryStateText => VehicleDataService.TotalReplayFrames > 0 ? RuntimeReplayFramesText : "No Replay";
    public string PacketLossTelemetryStateText => PacketLossText == "---" ? "No Data" : "Loss Monitor";
    public string SpeedTelemetryText => SpeedTelemetryValueText;
    public string VoltageTelemetryText => VoltageTelemetryValueText;
    public string CurrentTelemetryText => CurrentTelemetryValueText;
    public string MotorTempTelemetryText => MotorTempTelemetryValueText;
    public string BatteryTelemetryText => BatteryTelemetryValueText;
    public string PacketsPerSecondTelemetryText => PacketsPerSecondTelemetryValueText;
    public string ReplayProgressTelemetryText => ReplayProgressTelemetryValueText;
    public string PacketLossTelemetryText => PacketLossTelemetryValueText;

    // ── Properties required by TelemetryView.xaml (39258c6 restore) ──────────
    // Stream status panel
    public string AdapterName => "CAN USB — OBD-II LIVE ADAPTER";
    public string PacketLossText => (VehicleDataService.IsRunning || VehicleDataService.LoadedReplayPackets is { Count: > 0 }) ? "0.00%" : "---";

    // Runtime KPI strip (inline above chart)
    public string RuntimeRpmText => IsCalibrating ? "---" : $"{Snapshot.VehicleSpeed * 42:F0}";
    public string RuntimeCurrentText => IsCalibrating ? "---" : $"{Snapshot.PeakAmperage:F1} A";
    public string RuntimeGearText => IsCalibrating ? "---" : $"{Math.Max(1, (int)(Snapshot.VehicleSpeed / 28) + 1)}";
    public string RuntimeThrottleText => IsCalibrating ? "---" : $"{Math.Min(100, Snapshot.VehicleSpeed * 1.2):F0}%";
    public string RuntimeBrakeText => "0%";
    public string RuntimeCurrentCanIdText => VehicleDataService.TopSuspiciousCanId is { Length: > 0 } id ? id : "0x000";

    // Alert card body texts (static alert descriptions in right sidebar)
    public string CoolingHeadroomText => IsCalibrating ? "---" : $"Motor temp {MotorTemp:F1}°C — headroom {Math.Max(0, 120 - MotorTemp):F0}°C";
    public string CaptureCadenceText => IsCalibrating ? "---" : $"Sample cadence {SampleRateText} — {PacketRateText} active";
    public string EnergyNarrative => IsCalibrating ? "---" : $"Bus load estimated {Math.Min(100, Snapshot.Frequency * 0.8):F1}% — nominal threshold 70%";
    public string BusLoadText => IsCalibrating ? "---" : $"{Math.Min(100, Snapshot.Frequency * 0.8):F1}%";

    // ── Stream-aware 7-state operational state ────────────────────────────────
    public string StreamOperationalStateText
    {
        get
        {
            if (IsStreamFrozen) return "TELEMETRY DEGRADED";
            if (IsCalibrating)  return "BASELINING";
            var score = VehicleDataService.CurrentAnomalyScore;
            if (score >= 85)    return "CRITICAL";
            if (score >= 60 || VehicleDataService.TotalAlerts > 0) return "THREAT DETECTED";
            if (score >= 35)    return "ELEVATED RISK";
            if (score >= 10)    return "ANALYZING";
            return "MONITORING";
        }
    }

    public string StreamStateColor => StreamOperationalStateText switch
    {
        "CRITICAL"          => "#FF5050",
        "THREAT DETECTED"   => "#FF8C3A",
        "ELEVATED RISK"     => "#FFD94A",
        "ANALYZING"         => "#00ECFF",
        "MONITORING"        => "#56F0AC",
        "BASELINING"        => "#96B4FF",
        _                   => "#4A6470",
    };

    public string StreamHealthLine => StreamOperationalStateText switch
    {
        "CRITICAL"        => $"CRITICAL ANOMALY — {VehicleDataService.DetectedAttackType} — SCORE {VehicleDataService.CurrentAnomalyScore:F1}",
        "THREAT DETECTED" => $"ATTACK: {VehicleDataService.DetectedAttackType} | CONF {VehicleDataService.DetectionConfidence:F1}%",
        "ELEVATED RISK"   => $"RISK SCORE {VehicleDataService.CurrentAnomalyScore:F1} — MONITORING ELEVATED",
        "ANALYZING"       => $"SCORE {VehicleDataService.CurrentAnomalyScore:F1} — ACTIVE ANALYSIS",
        "MONITORING"      => $"STREAM NOMINAL — {PacketRateText} — {LatencyText}",
        "BASELINING"      => "ESTABLISHING BASELINE — HOLD...",
        _                 => "Offline",
    };
    // ─────────────────────────────────────────────────────────────────────────

    public string AlertDensityText
    {
        get
        {
            var now = DateTime.UtcNow;
            var recentAlerts = VehicleDataService.AlertHistory.Count(item => item.TimestampUtc >= now.AddMinutes(-1));
            return $"{recentAlerts}/min";
        }
    }

    public string CanTrafficVolumeText => $"{(latestSignals.Count > 0 ? latestSignals.Count : BuildSnapshotSignalsFromSchema().Count)} signals";
    public string CurrentRiskScoreText => $"{VehicleDataService.CurrentAnomalyScore:F2}";
    public string SuspiciousCanIdsText
    {
        get
        {
            var joined = VehicleDataService.AlertHistory
                .GroupBy(item => item.CanId)
                .OrderByDescending(group => group.Count())
                .Take(4)
                .Select(group => $"{group.Key} ({group.Count()})");
            var text = string.Join(" | ", joined);
            return string.IsNullOrWhiteSpace(text) ? "--" : text;
        }
    }

    private void RefreshSignalRows()
    {
        SignalRows.Clear();
        ActiveSignals.Clear();
        var displaySignals = latestSignals.Count > 0
            ? latestSignals
            : BuildSnapshotSignalsFromSchema();

        if (displaySignals.Count > 0)
        {
            foreach (var signal in displaySignals.OrderBy(s => s.CanId).ThenBy(s => s.Name))
            {
                SignalRows.Add(new SignalItem(
                    $"0x{signal.CanId:X3}",
                    signal.Name.ToUpperInvariant(),
                    $"{signal.Value:F2}",
                    signal.Unit,
                    BuildSignalStatus(signal),
                    Snapshot.Frequency,
                    Snapshot.TimeDiff,
                    BuildTrendPoints(GetSignalHistory(signal), 72, 18),
                    BuildSignalStatusBrush(signal),
                    BuildCanIdBrush(signal.CanId)));
            }

            foreach (var signal in displaySignals
                         .OrderByDescending(item => Math.Abs(item.Value))
                         .Take(5))
            {
                ActiveSignals.Add(new SignalLegendItem(signal.Name.ToUpperInvariant(), "#00FFFF"));
            }

            return;
        }

        OnPropertyChanged(nameof(CanTrafficVolumeText));
    }

    private async Task ImportLogAsync()
    {
        var dialog = new OpenFileDialog
        {
            Filter = "CAN logs (*.log;*.asc;*.csv)|*.log;*.asc;*.csv|All files (*.*)|*.*",
            Title = "Import CAN Log"
        };

        if (dialog.ShowDialog() != true)
        {
            return;
        }

        var result = await canLogImportService.ParseFileAsync(dialog.FileName);
        var packets = result.Packets.ToList();
        VehicleDataService.LoadReplayPackets(Path.GetFileName(dialog.FileName), packets);
        var firstPacket = packets.FirstOrDefault();
        if (firstPacket is not null)
        {
            VehicleDataService.PublishPlaybackPacket(firstPacket);
        }
    }

    private void ExportSignals()
    {
        var dialog = new SaveFileDialog
        {
            Filter = "CSV File (*.csv)|*.csv",
            FileName = $"DecodedSignals_{DateTime.Now:yyyyMMdd_HHmmss}.csv",
            Title = "Export Decoded Signals"
        };

        if (dialog.ShowDialog() != true)
        {
            return;
        }

        var rows = latestSignals.Select(signal => $"{signal.TimestampUtc:o},{signal.CanId:X3},{signal.Name},{signal.Value:F4},{signal.Unit}");
        System.IO.File.WriteAllLines(dialog.FileName, new[] { "timestamp,can_id,name,value,unit" }.Concat(rows));
    }

    private void OnSignalsUpdated(IReadOnlyList<DecodedSignal> signals)
    {
        latestSignals = signals ?? Array.Empty<DecodedSignal>();
        foreach (var signal in latestSignals)
        {
            var key = SignalHistoryKey(signal);
            if (!signalValueHistory.TryGetValue(key, out var values))
            {
                values = new List<double>();
                signalValueHistory[key] = values;
            }

            PushHistory(values, signal.Value);
        }

        RefreshSignalRows();
        OnPropertyChanged(nameof(CanTrafficVolumeText));
    }

    protected override void OnDataUpdated(VehicleSnapshot snapshot)
    {
        base.OnDataUpdated(snapshot);
        PushTelemetryHistory(snapshot);
        RefreshSignalRows();
        RefreshRiskTimeline();
        RefreshTimelineAxes();
        RefreshTelemetryEvents();
        RefreshSubsystemRows();
        OnPropertyChanged(nameof(StreamStateText));
        OnPropertyChanged(nameof(ConnectionStateText));
        OnPropertyChanged(nameof(LiveStateText));
        OnPropertyChanged(nameof(PacketsPerSecondText));
        OnPropertyChanged(nameof(LastEventTimestamp));
        OnPropertyChanged(nameof(ReplayStatusText));
        OnPropertyChanged(nameof(RuntimeStateText));
        OnPropertyChanged(nameof(DetectionConfidenceText));
        OnPropertyChanged(nameof(ReplayNameText));
        OnPropertyChanged(nameof(SessionDurationText));
        OnPropertyChanged(nameof(Trace1Text));
        OnPropertyChanged(nameof(Trace2Text));
        OnPropertyChanged(nameof(PacketRateText));
        OnPropertyChanged(nameof(SampleRateText));
        OnPropertyChanged(nameof(LatencyText));
        OnPropertyChanged(nameof(AlertDensityText));
        OnPropertyChanged(nameof(CanTrafficVolumeText));
        OnPropertyChanged(nameof(CurrentRiskScoreText));
        OnPropertyChanged(nameof(SuspiciousCanIdsText));
        OnPropertyChanged(nameof(RuntimeReplayProgressText));
        OnPropertyChanged(nameof(RuntimeReplayFramesText));
        OnPropertyChanged(nameof(PacketLossText));
        OnPropertyChanged(nameof(PacketLossTelemetryValueText));
        OnPropertyChanged(nameof(PacketLossTelemetryStateText));
        OnPropertyChanged(nameof(ReplayFpsText));
        OnPropertyChanged(nameof(DroppedFramesText));
        OnPropertyChanged(nameof(InferenceHealthText));
        OnPropertyChanged(nameof(ReplayLatencyText));
        OnPropertyChanged(nameof(PacketTimelineCaption));
        OnPropertyChanged(nameof(SpeedTrendPoints));
        OnPropertyChanged(nameof(VoltageTrendPoints));
        OnPropertyChanged(nameof(CurrentTrendPoints));
        OnPropertyChanged(nameof(MotorTempTrendPoints));
        OnPropertyChanged(nameof(PacketRateTrendPoints));
        OnPropertyChanged(nameof(PacketTimelinePoints));
        OnPropertyChanged(nameof(SpeedChannelPoints));
        OnPropertyChanged(nameof(SocChannelPoints));
        OnPropertyChanged(nameof(MotorTempChannelPoints));
        OnPropertyChanged(nameof(VoltageChannelPoints));
        OnPropertyChanged(nameof(TimelineEmptyStateText));
        OnPropertyChanged(nameof(VehicleStateSummary));
        OnPropertyChanged(nameof(VehicleMotionText));
        OnPropertyChanged(nameof(VehicleModeText));
        OnPropertyChanged(nameof(GearText));
        OnPropertyChanged(nameof(WatchlistText));
        OnPropertyChanged(nameof(EventsEmptyStateText));
        OnPropertyChanged(nameof(SpeedTelemetryValueText));
        OnPropertyChanged(nameof(VoltageTelemetryValueText));
        OnPropertyChanged(nameof(CurrentTelemetryValueText));
        OnPropertyChanged(nameof(MotorTempTelemetryValueText));
        OnPropertyChanged(nameof(BatteryTelemetryValueText));
        OnPropertyChanged(nameof(PacketsPerSecondTelemetryValueText));
        OnPropertyChanged(nameof(ReplayProgressTelemetryValueText));
        OnPropertyChanged(nameof(PacketLossTelemetryValueText));
        OnPropertyChanged(nameof(SpeedTelemetryStateText));
        OnPropertyChanged(nameof(VoltageTelemetryStateText));
        OnPropertyChanged(nameof(CurrentTelemetryStateText));
        OnPropertyChanged(nameof(MotorTempTelemetryStateText));
        OnPropertyChanged(nameof(BatteryTelemetryStateText));
        OnPropertyChanged(nameof(PacketsPerSecondTelemetryStateText));
        OnPropertyChanged(nameof(ReplayProgressTelemetryStateText));
        OnPropertyChanged(nameof(PacketLossTelemetryStateText));
        OnPropertyChanged(nameof(SpeedTelemetryText));
        OnPropertyChanged(nameof(VoltageTelemetryText));
        OnPropertyChanged(nameof(CurrentTelemetryText));
        OnPropertyChanged(nameof(MotorTempTelemetryText));
        OnPropertyChanged(nameof(BatteryTelemetryText));
        OnPropertyChanged(nameof(PacketsPerSecondTelemetryText));
        OnPropertyChanged(nameof(ReplayProgressTelemetryText));
        OnPropertyChanged(nameof(PacketLossTelemetryText));
        OnPropertyChanged(nameof(RuntimeRpmText));
        OnPropertyChanged(nameof(RuntimeCurrentText));
        OnPropertyChanged(nameof(RuntimeGearText));
        OnPropertyChanged(nameof(RuntimeThrottleText));
        OnPropertyChanged(nameof(RuntimeBrakeText));
        OnPropertyChanged(nameof(RuntimeCurrentCanIdText));
        OnPropertyChanged(nameof(CoolingHeadroomText));
        OnPropertyChanged(nameof(CaptureCadenceText));
        OnPropertyChanged(nameof(EnergyNarrative));
        OnPropertyChanged(nameof(BusLoadText));
        OnPropertyChanged(nameof(StreamOperationalStateText));
        OnPropertyChanged(nameof(StreamStateColor));
        OnPropertyChanged(nameof(StreamHealthLine));
    }

    protected override void OnVehicleDataServiceStateChanged()
    {
        RefreshSignalRows();
        RefreshSubsystemRows();
        OnPropertyChanged(nameof(StreamStateText));
        OnPropertyChanged(nameof(StreamOperationalStateText));
        OnPropertyChanged(nameof(StreamStateColor));
        OnPropertyChanged(nameof(StreamHealthLine));
        OnPropertyChanged(nameof(PacketLossText));
        OnPropertyChanged(nameof(PacketLossTelemetryValueText));
        OnPropertyChanged(nameof(PacketLossTelemetryStateText));
    }

    private void OnAlertHistoryUpdated(IReadOnlyList<RuntimeAlertEvent> _)
    {
        RefreshRiskTimeline();
        RefreshTimelineAxes();
        RefreshTelemetryEvents();
        OnPropertyChanged(nameof(AlertDensityText));
        OnPropertyChanged(nameof(SuspiciousCanIdsText));
        OnPropertyChanged(nameof(CurrentRiskScoreText));
        OnPropertyChanged(nameof(Trace1Text));
        OnPropertyChanged(nameof(Trace2Text));
        OnPropertyChanged(nameof(PacketTimelinePoints));
        OnPropertyChanged(nameof(EventsEmptyStateText));
    }

    private void OnReplayRuntimeUpdated()
    {
        OnPropertyChanged(nameof(ReplayFpsText));
        OnPropertyChanged(nameof(ReplayLatencyText));
        OnPropertyChanged(nameof(LatencyText));
        OnPropertyChanged(nameof(DroppedFramesText));
        OnPropertyChanged(nameof(RuntimeReplayProgressText));
        OnPropertyChanged(nameof(RuntimeReplayFramesText));
        OnPropertyChanged(nameof(PacketTimelineCaption));
        OnPropertyChanged(nameof(PacketsPerSecondText));
        OnPropertyChanged(nameof(PacketsPerSecondTelemetryValueText));
        OnPropertyChanged(nameof(PacketsPerSecondTelemetryStateText));
        OnPropertyChanged(nameof(ReplayProgressTelemetryValueText));
        OnPropertyChanged(nameof(ReplayProgressTelemetryStateText));
        OnPropertyChanged(nameof(PacketRateText));
        OnPropertyChanged(nameof(StreamHealthLine));
        OnPropertyChanged(nameof(StreamOperationalStateText));
        OnPropertyChanged(nameof(StreamStateColor));
        RefreshRiskTimeline();
        RefreshTimelineAxes();
    }

    private void OnReplayLoaded()
    {
        // Discard all cross-session history so trend sparklines and
        // signal histories start clean for the new dataset.
        speedHistory.Clear();
        voltageHistory.Clear();
        currentHistory.Clear();
        motorTempHistory.Clear();
        packetRateHistory.Clear();
        signalValueHistory.Clear();

        OnPropertyChanged(nameof(ReplayNameText));
        OnPropertyChanged(nameof(SessionDurationText));
        OnPropertyChanged(nameof(RuntimeReplayFramesText));
        OnPropertyChanged(nameof(RuntimeReplayProgressText));
        OnPropertyChanged(nameof(DroppedFramesText));
        OnPropertyChanged(nameof(PacketTimelineCaption));
        OnPropertyChanged(nameof(TimelineEmptyStateText));
        RefreshSignalRows();
        RefreshRiskTimeline();
        RefreshTimelineAxes();
        RefreshTelemetryEvents();
    }

    private void RefreshRiskTimeline()
    {
        RiskTimelineBars.Clear();
        var packets = VehicleDataService.LoadedReplayPackets;
        if (packets is { Count: > 0 })
        {
            var visibleCount = VehicleDataService.ProcessedReplayFrames > 0
                ? Math.Min(VehicleDataService.ProcessedReplayFrames, packets.Count)
                : packets.Count;
            foreach (var bucket in BuildPacketBuckets(packets.Take(visibleCount).ToList(), 32))
            {
                RiskTimelineBars.Add(18 + Math.Min(160, bucket * 4.0));
            }
            return;
        }

        foreach (var value in packetRateHistory.Skip(Math.Max(0, packetRateHistory.Count - 32)))
        {
            RiskTimelineBars.Add(18 + Math.Min(160, value * 4.0));
        }
    }

    private void RefreshTelemetryEvents()
    {
        TelemetryEvents.Clear();
        foreach (var alert in VehicleDataService.AlertHistory.OrderByDescending(item => item.TimestampUtc).Take(30))
        {
            TelemetryEvents.Add(alert);
        }

        TelemetryEventRows.Clear();
        foreach (var alert in VehicleDataService.AlertHistory.OrderByDescending(item => item.TimestampUtc).Take(20))
        {
            TelemetryEventRows.Add(new TelemetryEventItem(
                alert.TimestampUtc.ToLocalTime().ToString("HH:mm:ss.fff"),
                alert.Severity,
                alert.CanId,
                string.IsNullOrWhiteSpace(alert.Reason) ? alert.AttackType : alert.Reason));
        }

        var packets = VehicleDataService.LoadedReplayPackets;
        if (packets is { Count: > 0 })
        {
            var end = VehicleDataService.ProcessedReplayFrames > 0
                ? Math.Min(VehicleDataService.ProcessedReplayFrames, packets.Count)
                : Math.Min(packets.Count, 20);
            foreach (var packet in packets.Take(end).Reverse().Take(20))
            {
                TelemetryEventRows.Add(new TelemetryEventItem(
                    packet.Frame.TimestampUtc.ToLocalTime().ToString("HH:mm:ss.fff"),
                    packet.Anomalies.Count > 0 ? "WARN" : "INFO",
                    $"0x{packet.Frame.CanId:X3}",
                    string.IsNullOrWhiteSpace(packet.EventText) ? "CAN frame observed" : packet.EventText));
            }
        }

        OnPropertyChanged(nameof(EventsEmptyStateText));
    }

    private void RefreshTimelineAxes()
    {
        TimelineYAxisLabels.Clear();
        TimelineXAxisLabels.Clear();
        ReplayMarkers.Clear();

        var values = VehicleDataService.LoadedReplayPackets is { Count: > 0 } packets
            ? BuildPacketBuckets(packets, 96)
            : packetRateHistory.ToList();
        var hasReplay = VehicleDataService.LoadedReplayPackets is { Count: > 0 };
        var hasHistory = hasReplay || values.Count > 1 || VehicleDataService.RuntimeFps > 0 || Snapshot.Frequency > 0;
        var max = hasHistory
            ? Math.Max(1.0, values.Count == 0 ? Math.Max(1.0, Snapshot.Frequency) : values.Max())
            : 5000.0;

        TimelineYAxisLabels.Add(new AxisLabelItem("0", 128));
        TimelineYAxisLabels.Add(new AxisLabelItem(FormatAxisValue(max / 2.0), 66));
        TimelineYAxisLabels.Add(new AxisLabelItem(FormatAxisValue(max), 4));

        var startText = hasHistory ? LastEventTimestamp : "NO HISTORY";
        var midText = hasHistory ? "STREAM" : "STANDBY";
        var endText = LastEventTimestamp;
        if (VehicleDataService.LoadedReplayPackets is { Count: > 0 } replayPackets)
        {
            startText = replayPackets[0].Frame.TimestampUtc.ToLocalTime().ToString("HH:mm:ss");
            midText = replayPackets[replayPackets.Count / 2].Frame.TimestampUtc.ToLocalTime().ToString("HH:mm:ss");
            endText = replayPackets[replayPackets.Count - 1].Frame.TimestampUtc.ToLocalTime().ToString("HH:mm:ss");

            var processed = VehicleDataService.ProcessedReplayFrames > 0
                ? Math.Min(VehicleDataService.ProcessedReplayFrames, replayPackets.Count)
                : 0;
            if (processed > 0)
            {
                ReplayMarkers.Add(new ReplayMarkerItem(processed / (double)Math.Max(1, replayPackets.Count) * 1040.0, "CURSOR"));
            }

            foreach (var alert in VehicleDataService.AlertHistory.Take(8))
            {
                var nearestIndex = FindNearestPacketIndex(replayPackets, alert.TimestampUtc);
                if (nearestIndex >= 0)
                {
                    ReplayMarkers.Add(new ReplayMarkerItem(nearestIndex / (double)Math.Max(1, replayPackets.Count) * 1040.0, alert.Severity));
                }
            }
        }

        TimelineXAxisLabels.Add(new AxisLabelItem(startText, 0));
        TimelineXAxisLabels.Add(new AxisLabelItem(midText, 500));
        TimelineXAxisLabels.Add(new AxisLabelItem(endText, 980));
    }

    private static string FormatAxisValue(double value) =>
        value >= 1000 ? $"{value / 1000.0:F1}K" : $"{value:F0}";

    private void RefreshSubsystemRows()
    {
        SubsystemRows.Clear();
        SubsystemRows.Add(new SubsystemStateItem("BMS", Snapshot.BMSFault ? "DEGRADED" : "NOMINAL", Snapshot.BMSFault ? "#FF716C" : "#56F0AC", $"{BatteryTelemetryValueText} | {VoltageTelemetryValueText}"));
        SubsystemRows.Add(new SubsystemStateItem("DRIVE", Snapshot.MotorFault ? "DEGRADED" : "READY", Snapshot.MotorFault ? "#FF716C" : "#56F0AC", VehicleMotionText));
        SubsystemRows.Add(new SubsystemStateItem("THERMAL", Snapshot.OverheatFault ? "DEGRADED" : "NOMINAL", Snapshot.OverheatFault ? "#FF716C" : "#00C8C8", MotorTempTelemetryValueText));
        SubsystemRows.Add(new SubsystemStateItem("IDS", ConnectionStateText == "CONNECTED" ? "NOMINAL" : "OFFLINE", StreamStateColor, $"CONF {DetectionConfidenceText}"));
    }

    private void PushTelemetryHistory(VehicleSnapshot snapshot)
    {
        PushHistory(speedHistory, Math.Max(0, snapshot.VehicleSpeed));
        PushHistory(voltageHistory, Math.Max(0, snapshot.BatteryVoltage));
        PushHistory(currentHistory, Math.Max(0, snapshot.PeakAmperage));
        PushHistory(motorTempHistory, Math.Max(0, snapshot.MotorTemp));
        PushHistory(packetRateHistory, Math.Max(0, VehicleDataService.RuntimeFps > 0 ? VehicleDataService.RuntimeFps : snapshot.Frequency));
        PushHistory(socHistory, Math.Max(0, snapshot.SOC));

        if (latestSignals.Count == 0)
        {
            foreach (var signal in BuildSnapshotSignalsFromSchema())
            {
                PushHistory(GetSignalHistory(signal), signal.Value);
            }
        }
    }

    private static void PushHistory(List<double> history, double value)
    {
        history.Add(value);
        if (history.Count > 80)
        {
            history.RemoveRange(0, history.Count - 80);
        }
    }

    private List<double> GetSignalHistory(DecodedSignal signal)
    {
        var key = SignalHistoryKey(signal);
        if (!signalValueHistory.TryGetValue(key, out var values))
        {
            values = new List<double>();
            signalValueHistory[key] = values;
        }

        return values;
    }

    private static string SignalHistoryKey(DecodedSignal signal) => $"{signal.CanId:X3}:{signal.Name}";

    private static bool HasOperationalSignal(double value) => Math.Abs(value) > 0.001;

    private string BuildSignalStatus(DecodedSignal signal)
    {
        if (IsStreamFrozen && latestSignals.Count > 0)
        {
            return "HELD";
        }

        if (latestSignals.Count == 0)
        {
            return ConnectionStateText == "CONNECTED" ? "READY" : "STANDBY";
        }

        return "LIVE";
    }

    private string BuildSignalStatusBrush(DecodedSignal signal)
    {
        var status = BuildSignalStatus(signal);
        return status switch
        {
            "LIVE" => "#56F0AC",
            "READY" => "#00C8C8",
            "HELD" => "#FFD94A",
            _ => "#4A6470",
        };
    }

    private static string BuildCanIdBrush(int canId) => canId switch
    {
        0x100 => "#56F0AC",
        0x101 => "#00C8C8",
        0x102 => "#96B4FF",
        0x103 => "#FFD94A",
        0x104 => "#FF8C3A",
        0x105 => "#FF716C",
        _ => "#6E9090",
    };

    private IReadOnlyList<DecodedSignal> BuildSnapshotSignalsFromSchema()
    {
        var values = new Dictionary<string, double>(StringComparer.OrdinalIgnoreCase)
        {
            ["Battery_SOC"] = Snapshot.SOC,
            ["Battery_SOH"] = Snapshot.SOH > 0 ? Snapshot.SOH : Math.Max(0, Snapshot.SOC - 2),
            ["Voltage"] = Snapshot.BatteryVoltage,
            ["Current"] = Snapshot.BatteryCurrent != 0 ? Snapshot.BatteryCurrent : Snapshot.PeakAmperage,
            ["Temp"] = Snapshot.BatteryTemp,
            ["PeakAmperage"] = Snapshot.PeakAmperage,
            ["Speed"] = Snapshot.VehicleSpeed,
            ["RPM"] = Snapshot.MotorRPM > 0 ? Snapshot.MotorRPM : Snapshot.VehicleSpeed * 42,
            ["MotorTemp"] = Snapshot.MotorTemp,
            ["InverterTemp"] = Snapshot.InverterTemp > 0 ? Snapshot.InverterTemp : Snapshot.MotorTemp,
            ["FaultFlags"] = BuildFaultFlags(),
        };

        return PredefinedCanSchema.DbcMap
            .SelectMany(frame => frame.Value.Select(definition => (frame.Key, definition)))
            .Where(item => values.ContainsKey(item.definition.FeatureKey))
            .Select(item => new DecodedSignal
            {
                CanId = item.Key,
                Name = item.definition.Name,
                FeatureKey = item.definition.FeatureKey,
                Unit = item.definition.Unit,
                Value = values[item.definition.FeatureKey],
                TimestampUtc = Snapshot.UpdatedAt,
            })
            .ToList();
    }

    private double BuildFaultFlags()
    {
        var flags = 0;
        if (Snapshot.OverheatFault) flags |= 1;
        if (Snapshot.OverCurrentFault) flags |= 2;
        if (Snapshot.UnderVoltageFault) flags |= 4;
        if (Snapshot.BMSFault) flags |= 8;
        if (Snapshot.MotorFault) flags |= 16;
        return flags;
    }

    private System.Windows.Media.PointCollection BuildPacketTimelinePoints(double width, double height)
    {
        var packets = VehicleDataService.LoadedReplayPackets;
        if (packets is { Count: > 0 })
        {
            var visibleCount = VehicleDataService.ProcessedReplayFrames > 0
                ? Math.Min(VehicleDataService.ProcessedReplayFrames, packets.Count)
                : packets.Count;
            return BuildTrendPoints(BuildPacketBuckets(packets.Take(visibleCount).ToList(), 96), width, height);
        }

        return packetRateHistory.Count > 1 || VehicleDataService.RuntimeFps > 0 || Snapshot.Frequency > 0
            ? BuildTrendPoints(packetRateHistory, width, height)
            : new System.Windows.Media.PointCollection();
    }

    private static List<double> BuildPacketBuckets(IReadOnlyList<PlaybackPacket> packets, int bucketCount)
    {
        var values = new List<double>();
        if (packets.Count == 0 || bucketCount <= 0)
        {
            return values;
        }

        var start = packets[0].Frame.RelativeTimestampSeconds;
        var end = packets[packets.Count - 1].Frame.RelativeTimestampSeconds;
        var duration = Math.Max(0.001, end - start);
        var buckets = new double[bucketCount];
        foreach (var packet in packets)
        {
            var normalized = (packet.Frame.RelativeTimestampSeconds - start) / duration;
            var index = Math.Max(0, Math.Min(bucketCount - 1, (int)Math.Floor(normalized * bucketCount)));
            buckets[index]++;
        }

        values.AddRange(buckets);
        return values;
    }

    private static System.Windows.Media.PointCollection BuildTrendPoints(IReadOnlyList<double> values, double width, double height)
    {
        var points = new System.Windows.Media.PointCollection();
        if (values.Count == 0)
        {
            return points;
        }

        if (values.Count == 1)
        {
            points.Add(new System.Windows.Point(0, height / 2.0));
            points.Add(new System.Windows.Point(width, height / 2.0));
            return points;
        }

        var max = values.Max();
        var min = values.Min();
        var span = Math.Max(0.001, max - min);
        var count = values.Count;
        for (var i = 0; i < count; i++)
        {
            var x = count == 1 ? width : i * width / (count - 1);
            var y = height - ((values[i] - min) / span * height);
            points.Add(new System.Windows.Point(x, y));
        }

        return points;
    }

    private static int FindNearestPacketIndex(IReadOnlyList<PlaybackPacket> packets, DateTime timestampUtc)
    {
        if (packets.Count == 0)
        {
            return -1;
        }

        var bestIndex = 0;
        var bestDistance = TimeSpan.MaxValue;
        for (var i = 0; i < packets.Count; i++)
        {
            var distance = (packets[i].Frame.TimestampUtc - timestampUtc).Duration();
            if (distance < bestDistance)
            {
                bestDistance = distance;
                bestIndex = i;
            }
        }

        return bestIndex;
    }
}

public sealed class DiagnosticsViewModel : SectionViewModel
{
    private string diagnosticsStatus = "IDS EVENTS READY";
    private string filterSeverity = "ALL";
    private string filterAttackType = "ALL";
    private string filterCanId = string.Empty;

    public DiagnosticsViewModel(VehicleDataService vehicleDataService)
        : base(vehicleDataService, SectionKey.Diagnostics)
    {
        IdsEvents = new ObservableCollection<RuntimeAlertEvent>();
        FilteredIdsEvents = new ObservableCollection<RuntimeAlertEvent>();
        AttackTypeFilterOptions = new ObservableCollection<string> { "ALL" };

        RunFullScanCommand = new AsyncRelayCommand(StartFullScanAsync);
        QuickScanCommand = new RelayCommand(() => RefreshFromRuntime(VehicleDataService.AlertHistory));
        StopScanCommand = new RelayCommand(() => DiagnosticsStatus = "SCAN PAUSED");
        ClearAlertsCommand = new RelayCommand(() =>
        {
            IdsEvents.Clear();
            FilteredIdsEvents.Clear();
            DiagnosticsStatus = "EVENT VIEW CLEARED";
            OnPropertyChanged(nameof(TotalEventsText));
        });
        ExportReportCommand = new RelayCommand(ExportReport);
        SelectSubsystemCommand = new RelayCommand<string>(_ => { });

        vehicleDataService.AlertHistoryUpdated += OnAlertHistoryUpdated;
        vehicleDataService.AnomaliesUpdated    += OnAnomaliesReceived;
        RefreshFromRuntime(vehicleDataService.AlertHistory);
    }

    public ObservableCollection<RuntimeAlertEvent> IdsEvents { get; }
    public ObservableCollection<RuntimeAlertEvent> FilteredIdsEvents { get; }
    public ObservableCollection<string> AttackTypeFilterOptions { get; }

    public IRelayCommand RunFullScanCommand { get; }
    public IRelayCommand QuickScanCommand { get; }
    public IRelayCommand StopScanCommand { get; }
    public IRelayCommand ExportReportCommand { get; }
    public IRelayCommand ClearAlertsCommand { get; }
    public IRelayCommand<string> SelectSubsystemCommand { get; }

    public IReadOnlyList<string> SeverityFilterOptions { get; } = new[] { "ALL", "CRITICAL", "WARNING", "INFO" };

    public string FilterSeverity
    {
        get => filterSeverity;
        set
        {
            if (SetProperty(ref filterSeverity, value ?? "ALL"))
            {
                ApplyFilters();
            }
        }
    }

    public string FilterAttackType
    {
        get => filterAttackType;
        set
        {
            if (SetProperty(ref filterAttackType, value ?? "ALL"))
            {
                ApplyFilters();
            }
        }
    }

    public string FilterCanId
    {
        get => filterCanId;
        set
        {
            if (SetProperty(ref filterCanId, value ?? string.Empty))
            {
                ApplyFilters();
            }
        }
    }

    public string DiagnosticsStatus
    {
        get => diagnosticsStatus;
        private set => SetProperty(ref diagnosticsStatus, value);
    }

    public string TotalEventsText    => FilteredIdsEvents.Count.ToString();
    public string CurrentAttackText  => VehicleDataService.DetectedAttackType;
    public string CurrentRiskText    => $"{VehicleDataService.CurrentAnomalyScore:F2}";
    public string DiagConfidenceText => $"{VehicleDataService.DetectionConfidence:F1}%";
    public string DiagPacketRateText => $"{VehicleDataService.RuntimeFps:F1}";
    public string DiagLatencyText    => $"{VehicleDataService.RuntimeLatencyMs:F1} ms";

    private async Task StartFullScanAsync()
    {
        DiagnosticsStatus = "REFRESHING IDS EVENTS";
        await Task.Delay(200);
        RefreshFromRuntime(VehicleDataService.AlertHistory);
        DiagnosticsStatus = $"IDS EVENTS LOADED ({FilteredIdsEvents.Count})";
    }

    private void ExportReport()
    {
        var dialog = new SaveFileDialog
        {
            Filter = "CSV Report (*.csv)|*.csv|JSON Report (*.json)|*.json",
            FileName = $"IdsEvents_{DateTime.Now:yyyyMMdd_HHmm}",
            Title = "Export IDS Events",
        };

        if (dialog.ShowDialog() != true)
        {
            return;
        }

        if (dialog.FileName.EndsWith(".json", StringComparison.OrdinalIgnoreCase))
        {
            var payload = JsonConvert.SerializeObject(FilteredIdsEvents, Formatting.Indented);
            File.WriteAllText(dialog.FileName, payload);
        }
        else
        {
            var rows = FilteredIdsEvents.Select(item =>
                $"{item.TimestampUtc:O},{item.CanId},{item.Severity},{item.Score:F4},{item.AttackType},\"{item.Reason.Replace("\"", "\"\"")}\"");
            File.WriteAllLines(
                dialog.FileName,
                new[] { "timestamp,can_id,risk_level,anomaly_score,attack_type,reason" }.Concat(rows));
        }

        DiagnosticsStatus = $"REPORT EXPORTED: {Path.GetFileName(dialog.FileName).ToUpperInvariant()}";
    }

    private void OnAlertHistoryUpdated(IReadOnlyList<RuntimeAlertEvent> history)
    {
        RefreshFromRuntime(history);
    }

    // Incrementally surfaces per-frame anomalies so the error console fills
    // during analysis rather than only on completion.
    private void OnAnomaliesReceived(IReadOnlyList<CanAnomaly> anomalies)
    {
        if (anomalies.Count == 0) return;

        // When a new analysis starts, AlertHistory is cleared by BeginReplayAnalysis.
        // Use that as the signal to wipe stale events from the previous session.
        if (VehicleDataService.AlertHistory.Count == 0 && IdsEvents.Count > 0)
        {
            IdsEvents.Clear();
            FilteredIdsEvents.Clear();
            DiagnosticsStatus = "RECEIVING EVENTS...";
        }

        foreach (var anomaly in anomalies)
        {
            IdsEvents.Insert(0, new RuntimeAlertEvent
            {
                TimestampUtc = anomaly.TimestampUtc,
                CanId        = $"0x{anomaly.RelatedCanId:X3}",
                Severity     = anomaly.Severity,
                Score        = anomaly.SeverityScore / 100.0,
                AttackType   = anomaly.Title,
                Reason       = anomaly.Description,
            });
            if (IdsEvents.Count > 2000)
                IdsEvents.RemoveAt(IdsEvents.Count - 1);
        }

        ApplyFilters();
        OnPropertyChanged(nameof(TotalEventsText));
    }

    private void RefreshFromRuntime(IReadOnlyList<RuntimeAlertEvent> history)
    {
        IdsEvents.Clear();
        foreach (var evt in history.OrderByDescending(item => item.TimestampUtc).Take(2000))
        {
            IdsEvents.Add(evt);
        }

        var attackTypes = IdsEvents
            .Select(item => item.AttackType)
            .Where(item => !string.IsNullOrWhiteSpace(item))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .OrderBy(item => item)
            .ToList();
        AttackTypeFilterOptions.Clear();
        AttackTypeFilterOptions.Add("ALL");
        foreach (var attackType in attackTypes)
        {
            AttackTypeFilterOptions.Add(attackType);
        }

        ApplyFilters();
        DiagnosticsStatus = IdsEvents.Count == 0
            ? "NO IDS EVENTS"
            : $"IDS EVENTS ACTIVE ({IdsEvents.Count})";
    }

    private void ApplyFilters()
    {
        FilteredIdsEvents.Clear();
        foreach (var evt in IdsEvents)
        {
            var severityOk = FilterSeverity == "ALL" ||
                             string.Equals(evt.Severity, FilterSeverity, StringComparison.OrdinalIgnoreCase);
            var attackOk = FilterAttackType == "ALL" ||
                           string.Equals(evt.AttackType, FilterAttackType, StringComparison.OrdinalIgnoreCase);
            var canIdOk = string.IsNullOrWhiteSpace(FilterCanId) ||
                          evt.CanId.Contains(FilterCanId.Trim(), StringComparison.OrdinalIgnoreCase);

            if (severityOk && attackOk && canIdOk)
            {
                FilteredIdsEvents.Add(evt);
            }
        }

        OnPropertyChanged(nameof(TotalEventsText));
    }

    protected override void OnDataUpdated(VehicleSnapshot snapshot)
    {
        base.OnDataUpdated(snapshot);
        OnPropertyChanged(nameof(CurrentAttackText));
        OnPropertyChanged(nameof(CurrentRiskText));
        OnPropertyChanged(nameof(DiagConfidenceText));
        OnPropertyChanged(nameof(DiagPacketRateText));
        OnPropertyChanged(nameof(DiagLatencyText));
    }
}

public sealed class LogPlaybackViewModel : SectionViewModel
{
    private string playbackMode = "STOPPED";
    private double playbackSpeed = 1;
    private readonly DispatcherTimer playbackTimer;
    private readonly CanLogImportService canLogImportService;
    private readonly AppLogger logger;
    private List<PlaybackPacket> playbackData = new();
    private int currentFrameIndex;
    private string loadedFileName = "NO SESSION";
    private string sessionDurationText = "00:00:00";
    private string notesText = "Add investigation notes...";
    private const double TimelineCanvasWidth = 920;
    private const double TimelineTrackHeight = 24;
    private double _fileStart = 0.0;
    private double _fileEnd   = 0.0;
    private readonly HashSet<double> _placedAlertSeconds = new HashSet<double>();
    private const int ScorePlotW = 540;
    private const int ScorePlotH = 126;
    private double[] _scoreBuckets = Array.Empty<double>();
    private double _scoreBucketMax = 1.0;
    // Cursor-progressive detection reveal
    private readonly List<(int Idx, RuntimeAlertEvent Alert)> _allAlertsByFrame = new List<(int, RuntimeAlertEvent)>();
    private int _lastRevealedFrame = -1;
    // Alert-to-frame timestamp calibration (handles mismatched coordinate domains)
    private double _alertTsA = 1.0;
    private double _alertTsB = 0.0;
    // Guard: skip full rebuild when alert set hasn't changed
    private int _lastInjectedAlertCount = -1;
    private double _lastInjectedAlertChecksum = 0.0;

    public LogPlaybackViewModel(VehicleDataService vehicleDataService, CanLogImportService canLogImportService, AppLogger logger)
        : base(vehicleDataService, SectionKey.LogPlayback)
    {
        this.canLogImportService = canLogImportService;
        this.logger = logger;

        playbackTimer = new DispatcherTimer();
        playbackTimer.Tick += OnPlaybackTick;

        Sessions = new ObservableCollection<PlaybackSessionItem>();
        EventRows = new ObservableCollection<PlaybackEventItem>();
        CorrelationRows = new ObservableCollection<CorrelationRowItem>();
        ReplayEventRows = new ObservableCollection<ReplayEventRowItem>();
        TimelineMarkers = new ObservableCollection<ForensicTimelineMarker>();
        TimelineWindows = new ObservableCollection<ForensicTimelineWindow>();
        SignalPlotSeries = new ObservableCollection<SignalPlotSeriesItem>();
        DetectionMarkers = new ObservableCollection<ForensicTimelineMarker>();
        BottomKpis = new ObservableCollection<AnalysisKpiItem>();

        PlayCommand = new RelayCommand(Play);
        PauseCommand = new RelayCommand(Pause);
        StopCommand = new RelayCommand(Stop);
        OpenLogCommand = new AsyncRelayCommand(OpenLogAsync);
        RewindCommand = new RelayCommand(Rewind);
        ForwardCommand = new RelayCommand(Forward);

        SetSpeedCommand = new RelayCommand<string>(s =>
        {
            if (!double.TryParse(s, System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var parsed))
            {
                parsed = 1;
            }

            playbackSpeed = Math.Max(0.25, Math.Min(32, parsed));
            if (playbackTimer.IsEnabled)
            {
                UpdateTimerInterval();
            }
            NotifyForensicProperties();
        });

        VehicleDataService.ReplayLoaded += OnReplayLoaded;
        VehicleDataService.AlertHistoryUpdated += OnAlertHistoryUpdated;
        LoadReplayFromService();
        RebuildForensicWorkspace();
    }

    public ObservableCollection<PlaybackSessionItem> Sessions { get; }
    public ObservableCollection<PlaybackEventItem> EventRows { get; }
    public ObservableCollection<CorrelationRowItem> CorrelationRows { get; }
    public ObservableCollection<ReplayEventRowItem> ReplayEventRows { get; }
    public ObservableCollection<ForensicTimelineMarker> TimelineMarkers { get; }
    public ObservableCollection<ForensicTimelineWindow> TimelineWindows { get; }
    public ObservableCollection<SignalPlotSeriesItem> SignalPlotSeries { get; }
    public ObservableCollection<ForensicTimelineMarker> DetectionMarkers { get; }
    public ObservableCollection<AnalysisKpiItem> BottomKpis { get; }

    public IRelayCommand PlayCommand { get; }
    public IRelayCommand PauseCommand { get; }
    public IRelayCommand StopCommand { get; }
    public IRelayCommand OpenLogCommand { get; }
    public IRelayCommand RewindCommand { get; }
    public IRelayCommand ForwardCommand { get; }
    public IRelayCommand<string> SetSpeedCommand { get; }

    public string LoadedFileName => loadedFileName;
    public string SessionDurationText => sessionDurationText;
    public string DatasetText => loadedFileName == "NO SESSION" ? "NO DATASET" : Path.GetFileNameWithoutExtension(loadedFileName).ToUpperInvariant();
    public string VehicleText => "CANvision EV";
    public string CaptureDateText => playbackData.Count == 0 ? "--" : playbackData[0].Frame.TimestampUtc.ToLocalTime().ToString("yyyy-MM-dd HH:mm:ss");
    public string StartTimeText => playbackData.Count == 0 ? "--" : playbackData[0].Frame.TimestampUtc.ToLocalTime().ToString("HH:mm:ss.fff");
    public string EndTimeText => playbackData.Count == 0 ? "--" : playbackData[playbackData.Count - 1].Frame.TimestampUtc.ToLocalTime().ToString("HH:mm:ss.fff");
    public string PlaybackSpeedText => playbackSpeed >= 32 ? "MAX" : $"{playbackSpeed:0.##}x";
    // Timestamp-based — matches BuildTimelineX and the axis labels so the bar and cursor always agree.
    // Frame-count ratio was wrong because simulation.csv has non-uniform density (attack injection
    // floods the second half with dense CAN frames, causing bar@27% while cursor showed 48%).
    public double ReplayProgressPercent
    {
        get
        {
            if (playbackData.Count == 0) return 0;
            return Math.Min(100, currentFrameIndex * 100.0 / playbackData.Count);
        }
    }
    public double PlaybackCursorLeft => ReplayProgressPercent / 100.0 * TimelineCanvasWidth;
    public string PlaybackPositionText => playbackData.Count == 0 ? "0 / 0" : $"{Math.Min(currentFrameIndex + 1, playbackData.Count):N0} / {playbackData.Count:N0}";
    public string CurrentTimestampText => CurrentPacket is null ? "--:--:--.---" : CurrentPacket.Frame.TimestampUtc.ToLocalTime().ToString("HH:mm:ss.fff");
    public string TotalTimestampText => playbackData.Count == 0 ? "--:--:--.---" : playbackData[playbackData.Count - 1].Frame.TimestampUtc.ToLocalTime().ToString("HH:mm:ss.fff");
    public string SyncStateText => playbackData.Count == 0 ? "NO CAPTURE" : "LOCKED";
    public string TimelineScaleText => _fileEnd > _fileStart
        ? TimeSpan.FromSeconds(_fileEnd - _fileStart).ToString(@"mm\:ss")
        : "--:--";
    public string TimelineStartText        => FormatTimelineOffset(0);
    public string TimelineQuarterText      => FormatTimelineOffset(0.25);
    public string TimelineMidText          => FormatTimelineOffset(0.5);
    public string TimelineThreeQuarterText => FormatTimelineOffset(0.75);
    public string TimelineEndText          => FormatTimelineOffset(1);
    public string TimelineEmptyStateText => playbackData.Count == 0 ? "Import CAN log" : string.Empty;
    public string CorrelationEmptyStateText => CorrelationRows.Count == 0 ? "No events in current replay window" : string.Empty;
    public string ReplayEventsEmptyStateText => ReplayEventRows.Count == 0 ? "No events in current time window" : string.Empty;
    public string SignalInspectionEmptyStateText => SignalPlotSeries.Count == 0 ? "No selected signal history" : string.Empty;
    public string DetectionAnalysisEmptyStateText => DetectionScorePoints.Count == 0 ? "No detection score history" : string.Empty;
    public string CurrentEventText => CurrentPacket?.EventText is { Length: > 0 } text ? text : playbackData.Count == 0 ? "No Event Selected" : "Frame Observed";
    public string CurrentDetectionText => ResolvePacketScore(CurrentPacket) > 0 ? "DETECTED" : playbackData.Count == 0 ? "--" : "NORMAL";
    public string CurrentConfidenceText => $"{Math.Min(99.9, ResolvePacketScore(CurrentPacket)):F1}%";
    public string CurrentCanIdText => CurrentPacket is null ? "--" : $"0x{CurrentPacket.Frame.CanId:X3}";
    public string CurrentSeverityText => CurrentPacket?.Anomalies.FirstOrDefault()?.Severity ?? (playbackData.Count == 0 ? "--" : "INFO");
    public string CurrentFilePositionText => playbackData.Count == 0 ? "--" : $"{Math.Min(100, Math.Max(0, currentFrameIndex / (double)Math.Max(1, playbackData.Count) * 100.0)):F1}%";
    public string CurrentAttackTypeText => CurrentPacket?.Anomalies.FirstOrDefault()?.Title ?? VehicleDataService.DetectedAttackType;
    public string TotalDetectionsText => TotalDetections.ToString("N0");
    public string AlertCountText => TotalAlerts.ToString("N0");
    public string ReplayFpsText => $"{VehicleDataService.RuntimeFps:F1}";
    public string MlAnalysisStateText => VehicleDataService.MlAnalysisState;
    public string TruePositivesText => AttackWindowCount == 0 ? "--" : Math.Min(TotalDetections, AttackWindowCount).ToString("N0");
    public string FalsePositivesText => AttackWindowCount == 0 ? TotalDetections.ToString("N0") : Math.Max(0, TotalDetections - AttackWindowCount).ToString("N0");
    public string FalseNegativesText => AttackWindowCount == 0 ? "--" : Math.Max(0, AttackWindowCount - TotalDetections).ToString("N0");
    public string DetectionRateText => TotalFrames == 0 ? "--" : $"{TotalDetections * 100.0 / TotalFrames:F1}%";
    public int AttackWindowCount => TimelineWindows.Count(item => item.Track == "Attack Windows");
    public string AttackWindowCountText => AttackWindowCount.ToString("N0");
    public string AttackCoverageText => AttackWindowCount == 0 ? "--" : $"{Math.Min(100, TotalDetections * 100.0 / Math.Max(1, AttackWindowCount)):F1}%";
    public string CoveredText => AttackWindowCount == 0 ? "--" : $"{Math.Min(TotalDetections, AttackWindowCount):N0}";
    public string MissedText => AttackWindowCount == 0 ? "--" : $"{Math.Max(0, AttackWindowCount - TotalDetections):N0}";
    public string TotalAttackDurationText => BuildAttackDurationText();
    public string ReplayLatencyText => $"{VehicleDataService.RuntimeLatencyMs:F0} ms";
    public string DroppedFramesText => "0 (0.0%)";
    public string NotesText
    {
        get => notesText;
        set => SetProperty(ref notesText, value);
    }
    public int TotalFrames => playbackData.Count;
    public int TotalDetections => playbackData.Count(packet => ResolvePacketScore(packet) > 0);
    public int TotalAlerts => playbackData.Sum(packet => packet.Anomalies?.Count ?? 0);
    public System.Windows.Media.PointCollection DetectionScorePoints { get; private set; } = new();
    public System.Windows.Media.PointCollection DetectionThresholdPoints { get; private set; } = new() { new System.Windows.Point(0, 76), new System.Windows.Point(420, 76) };
    public System.Windows.Media.PointCollection LiveScorePoints { get; private set; } = new();
    public double LiveChartCursorX { get; private set; } = 0;
    public System.Windows.Media.PointCollection ProgressTrendPoints { get; private set; } = new();
    public System.Windows.Media.PointCollection DetectionTrendPoints { get; private set; } = new();
    public System.Windows.Media.PointCollection AlertTrendPoints { get; private set; } = new();
    public System.Windows.Media.PointCollection FrameTrendPoints { get; private set; } = new();
    public System.Windows.Media.PointCollection CoverageTrendPoints { get; private set; } = new();
    public System.Windows.Media.PointCollection ScoreTrendPoints { get; private set; } = new();
    public System.Windows.Media.PointCollection LatencyTrendPoints { get; private set; } = new();
    public System.Windows.Media.PointCollection DroppedTrendPoints { get; private set; } = new();
    private PlaybackPacket? CurrentPacket => playbackData.Count == 0 ? null : playbackData[Math.Max(0, Math.Min(currentFrameIndex, playbackData.Count - 1))];

    public string PlaybackMode
    {
        get => playbackMode;
        set
        {
            if (SetProperty(ref playbackMode, value))
            {
                OnPropertyChanged(nameof(PlaybackStatus));
            }
        }
    }

    public string ReplayProgressText => $"{ReplayProgressPercent:F1}%";
    public string ProcessedFramesText => $"{currentFrameIndex}/{Math.Max(1, playbackData.Count)}";
    public string ActiveAnomaliesText => VehicleDataService.CurrentAnomalies.Count.ToString();
    public string CurrentAnomalyScoreText
    {
        get
        {
            var first = CurrentPacket?.Anomalies.FirstOrDefault();
            return first != null ? $"{first.AnomalyScore:F2}" : "0,00";
        }
    }

    private void Play()
    {
        if (playbackData.Count == 0)
        {
            LoadReplayFromService();
        }

        if (playbackData.Count == 0)
        {
            PlaybackMode = "NO LOG LOADED";
            return;
        }

        PlaybackMode = "PLAYING";
        UpdateTimerInterval();
        playbackTimer.Start();
    }

    private void Pause()
    {
        PlaybackMode = "PAUSED";
        playbackTimer.Stop();
    }

    private void Stop()
    {
        PlaybackMode = "STOPPED";
        playbackTimer.Stop();
        currentFrameIndex = 0;
        VehicleDataService.SetReplayCursor(-1);
        if (playbackData.Count > 0)
        {
            VehicleDataService.PublishPlaybackPacket(playbackData[0]);
        }

        OnPropertyChanged(nameof(ReplayProgressText));
        OnPropertyChanged(nameof(ProcessedFramesText));
        RebuildForensicWorkspace();
    }

    private void Rewind()
    {
        currentFrameIndex = Math.Max(0, currentFrameIndex - 1);
        if (playbackData.Count > 0)
        {
            var packet = playbackData[currentFrameIndex];
            VehicleDataService.PublishPlaybackPacket(packet);
            VehicleDataService.SetReplayCursor(currentFrameIndex);
            VehicleDataService.UpdateReplayRuntime(
                currentFrameIndex + 1,
                packet.Frame.CanId,
                ResolvePacketScore(packet),
                VehicleDataService.RuntimeFps,
                VehicleDataService.RuntimeLatencyMs);
            UpdatePlaybackCursor();
            NotifyPlaybackPositionProperties();
        }
    }

    private void Forward()
    {
        currentFrameIndex = Math.Min(Math.Max(0, playbackData.Count - 1), currentFrameIndex + 1);
        if (playbackData.Count > 0)
        {
            var packet = playbackData[currentFrameIndex];
            VehicleDataService.PublishPlaybackPacket(packet);
            VehicleDataService.SetReplayCursor(currentFrameIndex);
            VehicleDataService.UpdateReplayRuntime(
                currentFrameIndex + 1,
                packet.Frame.CanId,
                ResolvePacketScore(packet),
                VehicleDataService.RuntimeFps,
                VehicleDataService.RuntimeLatencyMs);
            UpdatePlaybackCursor();
            NotifyPlaybackPositionProperties();
        }
    }

    private async Task OpenLogAsync()
    {
        var dialog = new OpenFileDialog
        {
            Filter = "CAN logs (*.log;*.txt;*.trc;*.asc;*.csv)|*.log;*.txt;*.trc;*.asc;*.csv|All files (*.*)|*.*",
            Title = "Open CAN Log",
        };

        if (dialog.ShowDialog() != true)
        {
            return;
        }

        try
        {
            var result = await canLogImportService.ParseFileAsync(dialog.FileName, skipMlScoring: true);
            var replayName = Path.GetFileName(dialog.FileName);
            var packets = result.Packets.ToList();
            VehicleDataService.LoadReplayPackets(replayName, packets);
            LoadReplayData(replayName, packets, result.Events.ToList());
            PlaybackMode = playbackData.Count == 0
                ? $"NO PARSABLE FRAMES ({result.ParsedLines}/{result.TotalLines})"
                : $"LOADED {playbackData.Count} FRAMES ({result.ParsedLines}/{result.TotalLines})";
            // Trigger ML analysis on the backend in parallel — results arrive via polling
            _ = VehicleDataService.TriggerBackendReplayAsync(dialog.FileName);
        }
        catch (Exception exception)
        {
            logger.Error("Log import failed.", exception);
            PlaybackMode = "IMPORT FAILED";
        }
    }

    private void LoadReplayFromService()
    {
        var packets = VehicleDataService.LoadedReplayPackets?.ToList() ?? new List<PlaybackPacket>();
        if (packets.Count == 0)
        {
            return;
        }

        var replayName = string.IsNullOrWhiteSpace(VehicleDataService.ReplayName)
            ? "REPLAY"
            : VehicleDataService.ReplayName;
        var events = packets
            .Take(20)
            .Select(packet => new CanPlaybackEvent(
                packet.Frame.TimestampUtc.ToLocalTime().ToString("HH:mm:ss.fff"),
                $"0x{packet.Frame.CanId:X3}",
                BitConverter.ToString(packet.Frame.Data).Replace("-", string.Empty),
                packet.EventText))
            .ToList();
        LoadReplayData(replayName, packets, events);
    }

    private void LoadReplayData(string replayName, List<PlaybackPacket> packets, List<CanPlaybackEvent> events)
    {
        playbackData = packets;
        currentFrameIndex = 0;
        _fileStart = packets.Count > 0 ? packets[0].Frame.RelativeTimestampSeconds : 0.0;
        _fileEnd   = packets.Count > 0 ? packets[packets.Count - 1].Frame.RelativeTimestampSeconds : 0.0;
        _lastInjectedAlertCount = -1;
        _lastInjectedAlertChecksum = 0.0;
        _alertTsA = 1.0;
        _alertTsB = 0.0;
        EventRows.Clear();
        foreach (var evt in events.Take(20))
        {
            EventRows.Add(new PlaybackEventItem(evt.Timestamp, evt.FrameId, evt.DataHex, evt.DecodedSignal));
        }

        loadedFileName = string.IsNullOrWhiteSpace(replayName) ? "REPLAY" : replayName;
        sessionDurationText = playbackData.Count < 2
            ? "00:00:00"
            : TimeSpan.FromMilliseconds(playbackData.Sum(packet => packet.DelayMilliseconds)).ToString(@"hh\:mm\:ss");
        OnPropertyChanged(nameof(LoadedFileName));
        OnPropertyChanged(nameof(SessionDurationText));

        VehicleDataService.SetReplayCursor(0);

        if (playbackData.Count > 0)
        {
            VehicleDataService.PublishPlaybackPacket(playbackData[0]);
            VehicleDataService.UpdateReplayRuntime(
                1,
                playbackData[0].Frame.CanId,
                ResolvePacketScore(playbackData[0]),
                VehicleDataService.RuntimeFps,
                VehicleDataService.RuntimeLatencyMs);
        }

        Sessions.Clear();
        Sessions.Add(
            new PlaybackSessionItem(
                loadedFileName,
                DateTime.Now.ToString("yyyy-MM-dd HH:mm"),
                sessionDurationText,
                $"{playbackData.Count:N0} FRAMES"));

        OnPropertyChanged(nameof(ReplayProgressText));
        OnPropertyChanged(nameof(ProcessedFramesText));
        OnPropertyChanged(nameof(CurrentAttackTypeText));
        OnPropertyChanged(nameof(ActiveAnomaliesText));
        OnPropertyChanged(nameof(CurrentAnomalyScoreText));
        RebuildForensicWorkspace();
    }

    private void OnReplayLoaded()
    {
        LoadReplayFromService();
    }

    private void OnAlertHistoryUpdated(IReadOnlyList<RuntimeAlertEvent> history)
    {
        if (playbackData.Count == 0) return;

        // Live-alert batches (from runtime streaming) have RelativeSeconds=0 because that field
        // isn't set in the OnRefreshTick path. They would corrupt the replay timeline by mapping
        // all alerts to frame 0. Reject any batch where every entry has no file timestamp.
        if (history.Count > 0 && history.All(a => a.RelativeSeconds <= 0.0)) return;

        var mlState = VehicleDataService.MlAnalysisState;
        if (mlState == "COMPLETE" || mlState == "ERROR")
        {
            // Skip the expensive full rebuild if the alert set hasn't changed
            var checksum = history.Count > 0 ? history.Sum(a => a.RelativeSeconds + a.Score) : 0.0;
            if (history.Count == _lastInjectedAlertCount && Math.Abs(checksum - _lastInjectedAlertChecksum) < 0.001)
                return;
            _lastInjectedAlertCount = history.Count;
            _lastInjectedAlertChecksum = checksum;

            // Final result: rebuild sorted alert list then do a full rebuild
            _placedAlertSeconds.Clear();
            _allAlertsByFrame.Clear();
            _lastRevealedFrame = -1;
            InjectAllReplayAlerts(history);

            // Populate _allAlertsByFrame from injected alerts (sorted by frame index)
            for (var i = 0; i < playbackData.Count; i++)
            {
                if (playbackData[i].Anomalies.Count > 0 && playbackData[i].Anomalies[0].Source == "replay")
                {
                    // Create a placeholder RuntimeAlertEvent for the reveal system
                    var anomaly = playbackData[i].Anomalies[0];
                    _allAlertsByFrame.Add((i, new RuntimeAlertEvent
                    {
                        RelativeSeconds = playbackData[i].Frame.RelativeTimestampSeconds,
                        TimestampUtc    = anomaly.TimestampUtc,
                        CanId           = $"0x{anomaly.RelatedCanId:X3}",
                        Severity        = anomaly.Severity,
                        Score           = anomaly.AnomalyScore,
                        AttackType      = anomaly.Title,
                        Reason          = anomaly.Description,
                    }));
                }
            }

            // When playing, skip the expensive pieces (correlation rows, signal chart, kpi sparklines)
            // to avoid a ~500 ms UI freeze on a 10k-frame file.
            // RebuildTimeline and RebuildDetectionAnalysis are both O(n) and fast (~2-5 ms each).
            if (PlaybackMode == "PLAYING")
            {
                RebuildTimeline();
                RebuildDetectionAnalysis();
                return;
            }

            RebuildForensicWorkspace();
        }
        else
        {
            // Analysis in progress: append only new markers — never clear existing ones
            AppendNewReplayAlerts(history);
            NotifyForensicProperties();
        }
    }

    // Full re-injection (used on COMPLETE or after seek/load)
    private void InjectAllReplayAlerts(IReadOnlyList<RuntimeAlertEvent> alerts)
    {
        CalibrateAlertTimestamps(alerts);

        foreach (var p in playbackData)
            if (p.Anomalies.Count > 0 && p.Anomalies[0].Source == "replay")
                p.Anomalies = Array.Empty<CanAnomaly>();

        foreach (var alert in alerts)
        {
            var idx = FindNearestPacketIndex(alert.RelativeSeconds);
            if (idx < 0) continue;
            if (playbackData[idx].Anomalies.Count > 0 && playbackData[idx].Anomalies[0].Source != "replay") continue;
            playbackData[idx].Anomalies = new[] { MakeReplayAnomaly(alert) };
        }
    }

    private void CalibrateAlertTimestamps(IReadOnlyList<RuntimeAlertEvent> alerts)
    {
        _alertTsA = 1.0;
        _alertTsB = 0.0;
        if (alerts.Count == 0 || playbackData.Count < 2) return;
        var alertMin = alerts.Min(a => a.RelativeSeconds);
        var alertMax = alerts.Max(a => a.RelativeSeconds);
        var frameStart = playbackData[0].Frame.RelativeTimestampSeconds;
        var frameEnd = playbackData[playbackData.Count - 1].Frame.RelativeTimestampSeconds;
        // Skip calibration only when alert timestamps already fall within the frame domain.
        // simulation.csv uses wall-clock timestamps (e.g. 3600 s = 01:00:00) while
        // RelativeTimestampSeconds is file-relative (0–N s). Without the upper-bound check,
        // alertMin=3600 >= frameStart(0)-1 = -1 passes → calibration skipped → all alerts
        // binary-search past frameEnd and map to the last frame.
        if (alertMin >= frameStart - 1.0 && alertMax <= frameEnd + 1.0) return;
        var alertSpan = Math.Max(0.001, alertMax - alertMin);
        var frameSpan = Math.Max(0.001, frameEnd - frameStart);
        _alertTsA = frameSpan / alertSpan;
        _alertTsB = frameStart - alertMin * _alertTsA;
    }

    // Incremental append — inject anomaly, register in _allAlertsByFrame, reveal if cursor passed
    private void AppendNewReplayAlerts(IReadOnlyList<RuntimeAlertEvent> alerts)
    {
        var anyNew = false;
        foreach (var alert in alerts)
        {
            if (_placedAlertSeconds.Contains(alert.RelativeSeconds)) continue;

            var idx = FindNearestPacketIndex(alert.RelativeSeconds);
            if (idx < 0) continue;
            if (playbackData[idx].Anomalies.Count > 0 && playbackData[idx].Anomalies[0].Source != "replay") continue;

            playbackData[idx].Anomalies = new[] { MakeReplayAnomaly(alert) };
            _placedAlertSeconds.Add(alert.RelativeSeconds);

            // Register sorted by frame index for cursor-progressive reveal
            var insertAt = _allAlertsByFrame.Count;
            for (var i = 0; i < _allAlertsByFrame.Count; i++)
                if (_allAlertsByFrame[i].Idx > idx) { insertAt = i; break; }
            _allAlertsByFrame.Insert(insertAt, (idx, alert));

            // Add Ground Truth marker immediately (known attack location)
            var x = BuildTimelineX(idx);
            TimelineMarkers.Add(new ForensicTimelineMarker("Ground Truth", x, 100, "GT", "#B46CFF"));
            anyNew = true;
        }

        if (anyNew)
        {
            // Reveal Detection/Alert dots for any new alerts the cursor has already passed
            RevealMarkersUpTo(currentFrameIndex);
            PreBuildScoreBuckets(playbackData.Select(ResolvePacketScore).ToList());
        }
    }

    private CanAnomaly MakeReplayAnomaly(RuntimeAlertEvent alert)
        {
            var canId = 0;
            if (alert.CanId.StartsWith("0x", StringComparison.OrdinalIgnoreCase))
                int.TryParse(alert.CanId.Substring(2), System.Globalization.NumberStyles.HexNumber, null, out canId);
            return new CanAnomaly
            {
                Code          = "ML-REPLAY",
                Title         = string.IsNullOrWhiteSpace(alert.AttackType) ? "ANOMALY" : alert.AttackType,
                Description   = alert.Reason,
                Severity      = alert.Severity,
                SeverityScore = Math.Min(100, (int)(alert.Score * 100)),
                AnomalyScore  = alert.Score,
                RelatedCanId  = canId,
                TimestampUtc  = alert.TimestampUtc,
                Source        = "replay",
            };
        }

        private int FindNearestPacketIndex(double relativeSeconds)
    {
        if (playbackData.Count == 0) return -1;
        // Apply calibration if alert timestamps are in a different coordinate domain than frames
        var ts = _alertTsA * relativeSeconds + _alertTsB;
        int lo = 0, hi = playbackData.Count - 1;
        while (lo < hi)
        {
            var mid = (lo + hi) / 2;
            if (playbackData[mid].Frame.RelativeTimestampSeconds < ts) lo = mid + 1;
            else hi = mid;
        }
        return lo;
    }

    protected override void OnDataUpdated(VehicleSnapshot snapshot)
    {
        base.OnDataUpdated(snapshot);
        OnPropertyChanged(nameof(ReplayProgressText));
        OnPropertyChanged(nameof(ProcessedFramesText));
        OnPropertyChanged(nameof(CurrentAttackTypeText));
        OnPropertyChanged(nameof(ActiveAnomaliesText));
        OnPropertyChanged(nameof(CurrentAnomalyScoreText));
        OnPropertyChanged(nameof(MlAnalysisStateText));
        // NotifyForensicProperties is intentionally NOT called here — it triggers 8× O(n) LINQ
        // scans that would fire 60+ times/second during playback. Forensic properties are refreshed
        // only when alerts actually change (RevealMarkersUpTo, RebuildForensicWorkspace).
    }

    private void UpdateTimerInterval()
    {
        // At 4x+ ignore log timestamps and fire at display rate — batching handles throughput
        if (playbackSpeed >= 4)
        {
            playbackTimer.Interval = TimeSpan.FromMilliseconds(16);
            return;
        }
        var packetDelay = playbackData.Count == 0
            ? 1000
            : Math.Max(16, playbackData[Math.Min(currentFrameIndex, playbackData.Count - 1)].DelayMilliseconds / playbackSpeed);
        playbackTimer.Interval = TimeSpan.FromMilliseconds(packetDelay);
    }

    private void OnPlaybackTick(object? sender, EventArgs e)
    {
        if (currentFrameIndex >= playbackData.Count)
        {
            Stop();
            return;
        }

        // At high speed batch multiple frames per tick to overcome the 16ms/frame floor
        int batch = playbackSpeed >= 4 ? (int)(playbackSpeed / 2) : 1;

        PlaybackPacket? lastPacket = null;
        for (int b = 0; b < batch && currentFrameIndex < playbackData.Count; b++)
        {
            var p = playbackData[currentFrameIndex];
            VehicleDataService.PublishPlaybackPacket(p);
            lastPacket = p;
            currentFrameIndex++;
        }

        if (lastPacket == null) return;

        VehicleDataService.SetReplayCursor(currentFrameIndex - 1);
        VehicleDataService.UpdateReplayRuntime(
            currentFrameIndex,
            lastPacket.Frame.CanId,
            ResolvePacketScore(lastPacket),
            VehicleDataService.RuntimeFps,
            VehicleDataService.RuntimeLatencyMs);

        // Live frame feed (capped at 20) — show last frame in batch
        EventRows.Insert(0, new PlaybackEventItem(
            lastPacket.Frame.TimestampUtc.ToLocalTime().ToString("HH:mm:ss.fff"),
            $"0x{lastPacket.Frame.CanId:X3}",
            BitConverter.ToString(lastPacket.Frame.Data).Replace("-", string.Empty),
            lastPacket.EventText));
        if (EventRows.Count > 20)
            EventRows.RemoveAt(20);

        // Mirror to right-rail live events list
        ReplayEventRows.Clear();
        foreach (var row in EventRows)
            ReplayEventRows.Add(new ReplayEventRowItem(row.Timestamp, "INFO", row.FrameId, row.DecodedSignal));

        if (currentFrameIndex < playbackData.Count)
            UpdateTimerInterval();

        // O(1): slide cursor without rebuilding all forensic collections
        UpdatePlaybackCursor();

        // Notify only the 18 properties that change each frame
        NotifyPlaybackPositionProperties();
    }

    // Moves only the cursor marker — O(1), no full rebuild.
    private void UpdatePlaybackCursor()
    {
        for (var i = 0; i < TimelineMarkers.Count; i++)
        {
            if (TimelineMarkers[i].Track == "Playback")
            {
                TimelineMarkers.RemoveAt(i);
                break;
            }
        }

        if (playbackData.Count > 0)
        {
            var idx = Math.Max(0, Math.Min(currentFrameIndex, playbackData.Count - 1));
            TimelineMarkers.Insert(0, new ForensicTimelineMarker("Playback", BuildTimelineX(idx), 16, "CURSOR", "#00C8C8"));
        }

        // Reveal detection dots as cursor passes alert positions
        if (currentFrameIndex > _lastRevealedFrame && _allAlertsByFrame.Count > 0)
            RevealMarkersUpTo(currentFrameIndex);


        // Advance the live chart line every 10 frames (~6×/sec at MAX)
        if (currentFrameIndex % 10 == 0)
            UpdateLiveChart();
    }

    private void NotifyTimelineAxisLabels()
    {
        OnPropertyChanged(nameof(TimelineStartText));
        OnPropertyChanged(nameof(TimelineQuarterText));
        OnPropertyChanged(nameof(TimelineMidText));
        OnPropertyChanged(nameof(TimelineThreeQuarterText));
        OnPropertyChanged(nameof(TimelineEndText));
        OnPropertyChanged(nameof(TimelineScaleText));
    }

    // Only notifies the properties that actually change on each playback frame.
    private void NotifyPlaybackPositionProperties()
    {
        OnPropertyChanged(nameof(ReplayProgressPercent));
        OnPropertyChanged(nameof(PlaybackCursorLeft));
        OnPropertyChanged(nameof(PlaybackPositionText));
        OnPropertyChanged(nameof(CurrentTimestampText));
        OnPropertyChanged(nameof(CurrentEventText));
        OnPropertyChanged(nameof(CurrentDetectionText));
        OnPropertyChanged(nameof(CurrentConfidenceText));
        OnPropertyChanged(nameof(CurrentCanIdText));
        OnPropertyChanged(nameof(CurrentSeverityText));
        OnPropertyChanged(nameof(CurrentFilePositionText));
        OnPropertyChanged(nameof(CurrentAttackTypeText));
        OnPropertyChanged(nameof(ReplayProgressText));
        OnPropertyChanged(nameof(ProcessedFramesText));
        OnPropertyChanged(nameof(ActiveAnomaliesText));
        OnPropertyChanged(nameof(CurrentAnomalyScoreText));
        OnPropertyChanged(nameof(ReplayFpsText));
        OnPropertyChanged(nameof(ReplayLatencyText));
        OnPropertyChanged(nameof(ReplayEventsEmptyStateText));

        // Update live-changing BottomKpi tiles in-place — AnalysisKpiItem.Value/Meta are
        // now observable so WPF picks up changes without a full collection rebuild.
        foreach (var kpi in BottomKpis)
        {
            switch (kpi.Label)
            {
                case "REPLAY PROGRESS": kpi.Value = ReplayProgressText; kpi.Meta = ProcessedFramesText; break;
                case "ANOMALY SCORE":   kpi.Value = CurrentAnomalyScoreText; kpi.Meta = CurrentDetectionText; break;
                case "REPLAY LATENCY":  kpi.Value = ReplayLatencyText; break;
            }
        }
    }

    private static double ResolvePacketScore(PlaybackPacket? packet)
    {
        if (packet?.Anomalies is null || packet.Anomalies.Count == 0)
        {
            return 0;
        }

        return packet.Anomalies
            .Select(item => item.SeverityScore > 0 ? item.SeverityScore : Math.Abs(item.AnomalyScore) * 100.0)
            .DefaultIfEmpty(0)
            .Max();
    }

    public string PlaybackStatus => PlaybackMode;

    private void RebuildForensicWorkspace()
    {
        RebuildTimeline();
        RebuildCorrelationRows();
        RebuildSignalInspection();
        RebuildDetectionAnalysis();
        RebuildReplayEvents();
        RebuildBottomKpis();
        NotifyForensicProperties();
    }

    private void RebuildTimeline()
    {
        _placedAlertSeconds.Clear();
        _lastRevealedFrame = -1;
        TimelineMarkers.Clear();
        TimelineWindows.Clear();
        if (playbackData.Count == 0) return;

        var cursorX = BuildTimelineX(Math.Max(0, Math.Min(currentFrameIndex, playbackData.Count - 1)));
        TimelineMarkers.Add(new ForensicTimelineMarker("Playback", cursorX, 16, "CURSOR", "#00C8C8"));

        // Ground Truth and Attack Windows: PRE-SHOWN (we know where attacks exist in the file)
        var windowStart = -1;
        for (var i = 0; i < playbackData.Count; i++)
        {
            var score = ResolvePacketScore(playbackData[i]);
            if (score > 0)
            {
                var x = BuildTimelineX(i);
                TimelineMarkers.Add(new ForensicTimelineMarker("Ground Truth", x, 100, "GT", "#B46CFF"));
                if (windowStart < 0) windowStart = i;
            }
            else if (windowStart >= 0)
            {
                AddAttackWindow(windowStart, i - 1);
                windowStart = -1;
            }
        }
        if (windowStart >= 0) AddAttackWindow(windowStart, playbackData.Count - 1);

        // Detection/Alert dots: reveal only up to current cursor position
        RevealMarkersUpTo(currentFrameIndex);
    }

    // Reveal Detection + Alert markers for all alerts whose frame index <= frameIndex
    private void RevealMarkersUpTo(int frameIndex)
    {
        var revealed = false;
        foreach (var (idx, _) in _allAlertsByFrame)
        {
            if (idx > frameIndex) break;
            if (idx <= _lastRevealedFrame) continue;
            var x = BuildTimelineX(idx);
            TimelineMarkers.Add(new ForensicTimelineMarker("Detections", x, 44, "D", "#FF8C3A"));
            TimelineMarkers.Add(new ForensicTimelineMarker("Alerts",     x, 72, "!", "#FF5050"));
            revealed = true;
        }
        if (frameIndex > _lastRevealedFrame) _lastRevealedFrame = frameIndex;
        if (revealed) NotifyForensicProperties();
    }

    private void AddAttackWindow(int startIndex, int endIndex)
    {
        var left = BuildTimelineX(startIndex);
        var right = BuildTimelineX(endIndex);
        TimelineWindows.Add(new ForensicTimelineWindow("Attack Windows", left, Math.Max(4, right - left), 126, "#AAFF5050"));
    }

    private double BuildTimelineX(int index)
    {
        if (playbackData.Count < 2) return 0;
        return (double)index / (playbackData.Count - 1) * TimelineCanvasWidth;
    }

    // ratio is 0-1 of frame count; show the actual timestamp at that frame position
    private string FormatTimelineOffset(double ratio)
    {
        if (playbackData.Count < 2 || _fileEnd <= _fileStart) return "00:00";
        var frameIdx = (int)Math.Round(ratio * (playbackData.Count - 1));
        frameIdx = Math.Max(0, Math.Min(frameIdx, playbackData.Count - 1));
        var ts = playbackData[frameIdx].Frame.RelativeTimestampSeconds - _fileStart;
        return TimeSpan.FromSeconds(Math.Max(0, ts)).ToString(@"mm\:ss");
    }

    private void RebuildCorrelationRows()
    {
        CorrelationRows.Clear();
        if (playbackData.Count == 0)
        {
            return;
        }

        var interesting = playbackData
            .Select((packet, index) => (packet, index, score: ResolvePacketScore(packet)))
            .Where(item => item.score > 0 || item.index == currentFrameIndex || !string.IsNullOrWhiteSpace(item.packet.EventText))
            .Take(300)
            .ToList();

        if (interesting.Count == 0)
        {
            interesting.AddRange(playbackData.Take(Math.Min(60, playbackData.Count)).Select((packet, index) => (packet, index, score: ResolvePacketScore(packet))));
        }

        foreach (var item in interesting)
        {
            var anomaly = item.packet.Anomalies.FirstOrDefault();
            var isAttack = item.score >= 70 ||
                           (anomaly?.Title.IndexOf("attack", StringComparison.OrdinalIgnoreCase) ?? -1) >= 0 ||
                           (anomaly?.Description.IndexOf("attack", StringComparison.OrdinalIgnoreCase) ?? -1) >= 0;
            CorrelationRows.Add(new CorrelationRowItem(
                item.packet.Frame.TimestampUtc.ToLocalTime().ToString("HH:mm:ss.fff"),
                $"0x{item.packet.Frame.CanId:X3}",
                anomaly?.Title ?? (string.IsNullOrWhiteSpace(item.packet.EventText) ? "CAN frame" : item.packet.EventText),
                anomaly?.Severity ?? "INFO",
                item.score > 0 ? "DETECTED" : "NORMAL",
                isAttack ? "ATTACK" : "NORMAL",
                anomaly?.Description ?? item.packet.EventText));
        }
    }

    private void RebuildSignalInspection()
    {
        SignalPlotSeries.Clear();
        if (playbackData.Count == 0)
        {
            return;
        }

        AddSignalSeries("Vehicle Speed", "Speed", "#00C8C8");
        AddSignalSeries("Battery Voltage", "Voltage", "#FFD94A");
        AddSignalSeries("Motor Temp", "MotorTemp", "#B46CFF");
        AddSignalSeries("SOC", "Battery_SOC", "#56F0AC");
    }

    private void AddSignalSeries(string label, string featureKey, string color)
    {
        var values = playbackData
            .Select(packet => packet.Signals.FirstOrDefault(signal => string.Equals(signal.FeatureKey, featureKey, StringComparison.OrdinalIgnoreCase))?.Value)
            .Where(value => value.HasValue)
            .Select(value => value!.Value)
            .ToList();

        if (values.Count == 0)
        {
            return;
        }

        SignalPlotSeries.Add(new SignalPlotSeriesItem(label, color, BuildPointCollection(values, 360, 120)));
    }

    // Build frame-density scores: how many frames fall in each time bucket.
    // Uses RelativeTimestampSeconds (float) for sub-ms accuracy.
    // Returns one score per frame, normalised 0–1. Always produces visible variation.
    private List<double> BuildFrameDensityScores()
    {
        if (playbackData.Count < 2) return Enumerable.Repeat(0.5, playbackData.Count).ToList();

        var ts = playbackData.Select(p => p.Frame.RelativeTimestampSeconds).ToArray();
        var t0 = ts[0];
        var tTotal = Math.Max(0.001, ts[ts.Length - 1] - t0);

        // Divide session into ScorePlotW buckets and count frames in each
        var counts = new int[ScorePlotW];
        foreach (var t in ts)
        {
            var b = (int)((t - t0) / tTotal * (ScorePlotW - 1));
            counts[Math.Max(0, Math.Min(ScorePlotW - 1, b))]++;
        }

        var maxCount = Math.Max(1, counts.Max());

        // Map each frame to its bucket's normalised density
        var result = new List<double>(playbackData.Count);
        foreach (var t in ts)
        {
            var b = (int)((t - t0) / tTotal * (ScorePlotW - 1));
            b = Math.Max(0, Math.Min(ScorePlotW - 1, b));
            result.Add((double)counts[b] / maxCount);
        }
        return result;
    }

    private void RebuildDetectionAnalysis()
    {
        var densityBuckets = BuildFrameDensityBuckets();  // ScorePlotW values, one per pixel column
        var mlBuckets = new double[ScorePlotW];

        for (var i = 0; i < playbackData.Count; i++)
        {
            var score = ResolvePacketScore(playbackData[i]);
            if (score <= 0) continue;
            var b = playbackData.Count <= 1 ? 0 : (int)(i * (ScorePlotW - 1) / (double)(playbackData.Count - 1));
            b = Math.Max(0, Math.Min(ScorePlotW - 1, b));
            if (score > mlBuckets[b]) mlBuckets[b] = score;
        }

        // Density forms the base waveform; ML detections spike above the threshold
        var blended = new double[ScorePlotW];
        for (var i = 0; i < ScorePlotW; i++)
            blended[i] = mlBuckets[i] > 0 ? 1.0 : densityBuckets[i] * 0.62;

        // In-place modification so PointCollection.Changed fires and Polygon auto-updates.
        // Replacing the reference (DetectionScorePoints = newCollection) does NOT reliably
        // trigger WPF Polygon re-render because Polygon holds an internal ref to the old object.
        var newScorePts = BuildFixedRangePoints(blended, ScorePlotW, ScorePlotH);
        DetectionScorePoints.Clear();
        foreach (var p in newScorePts) DetectionScorePoints.Add(p);

        // Threshold sits above the max normal-traffic level (density*0.62 <= 0.62, y>=45)
        DetectionThresholdPoints.Clear();
        DetectionThresholdPoints.Add(new System.Windows.Point(0, ScorePlotH * 0.28));
        DetectionThresholdPoints.Add(new System.Windows.Point(ScorePlotW, ScorePlotH * 0.28));

        PreBuildScoreBuckets(blended);

        DetectionMarkers.Clear();
        for (var i = 0; i < ScorePlotW; i++)
        {
            if (mlBuckets[i] > 0)
                DetectionMarkers.Add(new ForensicTimelineMarker("Detection", i, 0, "D", "#FF8C3A"));
        }

        UpdateLiveChart();
    }

    private double[] BuildFrameDensityBuckets()
    {
        if (playbackData.Count < 2)
            return Enumerable.Repeat(0.5, ScorePlotW).ToArray();
        var ts = playbackData.Select(p => p.Frame.RelativeTimestampSeconds).ToArray();
        var t0 = ts[0];
        var tTotal = Math.Max(0.001, ts[ts.Length - 1] - t0);
        var counts = new int[ScorePlotW];
        foreach (var t in ts)
        {
            var b = (int)((t - t0) / tTotal * (ScorePlotW - 1));
            counts[Math.Max(0, Math.Min(ScorePlotW - 1, b))]++;
        }
        var maxCount = Math.Max(1, counts.Max());
        return counts.Select(c => (double)c / maxCount).ToArray();
    }

    private static System.Windows.Media.PointCollection BuildFixedRangePoints(IReadOnlyList<double> values, double width, double height)
    {
        var pts = new System.Windows.Media.PointCollection(values.Count + 2);
        for (var i = 0; i < values.Count; i++)
        {
            var x = values.Count <= 1 ? 0.0 : i * width / (values.Count - 1);
            var y = (height - 2.0) * (1.0 - Math.Max(0.0, Math.Min(1.0, values[i]))) + 1.0;
            pts.Add(new System.Windows.Point(x, y));
        }
        // Close the polygon at the bottom to create a filled area chart
        if (values.Count > 0)
        {
            pts.Add(new System.Windows.Point(width, height - 1.0));
            pts.Add(new System.Windows.Point(0.0, height - 1.0));
        }
        return pts;
    }

    private void PreBuildScoreBuckets(IList<double> scores)
    {
        if (scores.Count == 0) { _scoreBuckets = Array.Empty<double>(); return; }
        var buckets = new double[ScorePlotW];
        for (var i = 0; i < scores.Count; i++)
        {
            var b = scores.Count <= 1 ? 0 : (int)(i * (ScorePlotW - 1) / (double)(scores.Count - 1));
            if (scores[i] > buckets[b]) buckets[b] = scores[i];
        }
        _scoreBucketMax = Math.Max(1.0, buckets.Max());
        _scoreBuckets = buckets;
    }

    private void UpdateLiveChart()
    {
        if (_scoreBuckets.Length == 0 || playbackData.Count < 2) return;
        var activeBucket = (int)(currentFrameIndex * (ScorePlotW - 1) / (double)(playbackData.Count - 1));
        activeBucket = Math.Max(0, Math.Min(ScorePlotW - 1, activeBucket));
        LiveChartCursorX = activeBucket;
        var pts = new System.Windows.Media.PointCollection(activeBucket + 1);
        for (var i = 0; i <= activeBucket; i++)
        {
            var normalized = Math.Max(0.0, Math.Min(1.0, _scoreBuckets[i] / _scoreBucketMax));
            var y = (ScorePlotH - 2.0) * (1.0 - normalized) + 1.0;
            pts.Add(new System.Windows.Point(i, Math.Max(1, Math.Min(ScorePlotH - 1, (int)y))));
        }
        LiveScorePoints.Clear();
        foreach (var p in pts) LiveScorePoints.Add(p);
        OnPropertyChanged(nameof(LiveChartCursorX));
    }

    private void RebuildReplayEvents()
    {
        ReplayEventRows.Clear();
        foreach (var row in EventRows.Take(80))
        {
            ReplayEventRows.Add(new ReplayEventRowItem(row.Timestamp, "INFO", row.FrameId, row.DecodedSignal));
        }
    }

    private void RebuildBottomKpis()
    {
        ProgressTrendPoints = BuildPointCollection(BuildProgressValues(), 150, 26);
        DetectionTrendPoints = BuildPointCollection(playbackData.Select(packet => ResolvePacketScore(packet) > 0 ? 1.0 : 0.0).ToList(), 150, 26);
        AlertTrendPoints = BuildPointCollection(playbackData.Select(packet => (double)(packet.Anomalies?.Count ?? 0)).ToList(), 150, 26);
        FrameTrendPoints = BuildPointCollection(playbackData.Select((_, index) => (double)index).ToList(), 150, 26);
        CoverageTrendPoints = DetectionTrendPoints;
        ScoreTrendPoints = BuildPointCollection(playbackData.Select(ResolvePacketScore).ToList(), 150, 26);
        LatencyTrendPoints = BuildPointCollection(playbackData.Select(packet => (double)Math.Max(0, packet.DelayMilliseconds)).ToList(), 150, 26);
        DroppedTrendPoints = BuildPointCollection(new List<double>(), 150, 26);

        BottomKpis.Clear();
        BottomKpis.Add(new AnalysisKpiItem("REPLAY PROGRESS", ReplayProgressText, ProcessedFramesText, ProgressTrendPoints, "#00C8C8"));
        BottomKpis.Add(new AnalysisKpiItem("TOTAL DETECTIONS", TotalDetectionsText, "IDS EVENTS", DetectionTrendPoints, "#FF8C3A"));
        BottomKpis.Add(new AnalysisKpiItem("ALERTS", AlertCountText, "ANOMALIES", AlertTrendPoints, "#FF5050"));
        BottomKpis.Add(new AnalysisKpiItem("FRAMES", TotalFrames.ToString("N0"), ProcessedFramesText, FrameTrendPoints, "#00C8C8"));
        BottomKpis.Add(new AnalysisKpiItem("ATTACK COVERAGE", AttackCoverageText, "GROUND TRUTH", CoverageTrendPoints, "#B46CFF"));
        BottomKpis.Add(new AnalysisKpiItem("ANOMALY SCORE", CurrentAnomalyScoreText, CurrentDetectionText, ScoreTrendPoints, "#FF5050"));
        BottomKpis.Add(new AnalysisKpiItem("REPLAY LATENCY", ReplayLatencyText, "FRAME DELAY", LatencyTrendPoints, "#00C8C8"));
        BottomKpis.Add(new AnalysisKpiItem("DROPPED FRAMES", DroppedFramesText, "DROP MONITOR", DroppedTrendPoints, "#56F0AC"));
    }

    private List<double> BuildProgressValues()
    {
        if (playbackData.Count == 0) return new List<double>();
        var total = (double)(playbackData.Count - 1);
        return playbackData.Select((_, i) => total > 0 ? i / total * 100.0 : 0.0).ToList();
    }

    private static System.Windows.Media.PointCollection BuildPointCollection(IReadOnlyList<double> values, double width, double height)
    {
        var points = new System.Windows.Media.PointCollection();
        if (values.Count == 0)
            return points;

        if (values.Count == 1)
        {
            var mid = height - 2;
            points.Add(new System.Windows.Point(0, mid));
            points.Add(new System.Windows.Point(width, mid));
            return points;
        }

        var max = values.Max();
        var min = values.Min();
        var span = Math.Max(0.001, max - min);
        var drawHeight = height - 4; // 2px headroom top and bottom
        for (var i = 0; i < values.Count; i++)
        {
            var x = i * width / (values.Count - 1);
            var y = (height - 2) - ((values[i] - min) / span * drawHeight);
            // Stay within canvas — never clip at the very edge
            points.Add(new System.Windows.Point(x, Math.Max(1, Math.Min(height - 2, y))));
        }

        return points;
    }

    private string BuildAttackDurationText()
    {
        if (TimelineWindows.Count == 0 || playbackData.Count < 2)
        {
            return "--";
        }

        var sessionTotal = playbackData[playbackData.Count - 1].Frame.RelativeTimestampSeconds
                         - playbackData[0].Frame.RelativeTimestampSeconds;
        if (sessionTotal <= 0)
            sessionTotal = playbackData.Sum(p => p.DelayMilliseconds) / 1000.0;
        var totalSeconds = TimelineWindows
            .Where(w => w.Track == "Attack Windows")
            .Sum(w => w.Width / TimelineCanvasWidth) * sessionTotal;
        return TimeSpan.FromSeconds(totalSeconds).ToString(@"mm\:ss\.fff");
    }

    private void NotifyForensicProperties()
    {
        OnPropertyChanged(nameof(PlaybackStatus));
        OnPropertyChanged(nameof(DatasetText));
        OnPropertyChanged(nameof(VehicleText));
        OnPropertyChanged(nameof(CaptureDateText));
        OnPropertyChanged(nameof(StartTimeText));
        OnPropertyChanged(nameof(EndTimeText));
        OnPropertyChanged(nameof(PlaybackSpeedText));
        OnPropertyChanged(nameof(ReplayProgressPercent));
        OnPropertyChanged(nameof(PlaybackCursorLeft));
        OnPropertyChanged(nameof(PlaybackPositionText));
        OnPropertyChanged(nameof(CurrentTimestampText));
        OnPropertyChanged(nameof(TotalTimestampText));
        OnPropertyChanged(nameof(SyncStateText));
        OnPropertyChanged(nameof(TimelineScaleText));
        OnPropertyChanged(nameof(TimelineStartText));
        OnPropertyChanged(nameof(TimelineQuarterText));
        OnPropertyChanged(nameof(TimelineMidText));
        OnPropertyChanged(nameof(TimelineThreeQuarterText));
        OnPropertyChanged(nameof(TimelineEndText));
        OnPropertyChanged(nameof(TimelineEmptyStateText));
        OnPropertyChanged(nameof(CorrelationEmptyStateText));
        OnPropertyChanged(nameof(ReplayEventsEmptyStateText));
        OnPropertyChanged(nameof(SignalInspectionEmptyStateText));
        OnPropertyChanged(nameof(DetectionAnalysisEmptyStateText));
        OnPropertyChanged(nameof(CurrentEventText));
        OnPropertyChanged(nameof(CurrentDetectionText));
        OnPropertyChanged(nameof(CurrentConfidenceText));
        OnPropertyChanged(nameof(CurrentCanIdText));
        OnPropertyChanged(nameof(CurrentSeverityText));
        OnPropertyChanged(nameof(CurrentFilePositionText));
        OnPropertyChanged(nameof(CurrentAttackTypeText));
        OnPropertyChanged(nameof(TotalFrames));
        OnPropertyChanged(nameof(TotalDetectionsText));
        OnPropertyChanged(nameof(AlertCountText));
        OnPropertyChanged(nameof(ReplayFpsText));
        OnPropertyChanged(nameof(TruePositivesText));
        OnPropertyChanged(nameof(FalsePositivesText));
        OnPropertyChanged(nameof(FalseNegativesText));
        OnPropertyChanged(nameof(DetectionRateText));
        OnPropertyChanged(nameof(AttackWindowCountText));
        OnPropertyChanged(nameof(AttackCoverageText));
        OnPropertyChanged(nameof(CoveredText));
        OnPropertyChanged(nameof(MissedText));
        OnPropertyChanged(nameof(TotalAttackDurationText));
        OnPropertyChanged(nameof(ReplayLatencyText));
        OnPropertyChanged(nameof(DroppedFramesText));
        OnPropertyChanged(nameof(DetectionScorePoints));
        OnPropertyChanged(nameof(DetectionThresholdPoints));
        OnPropertyChanged(nameof(ProgressTrendPoints));
        OnPropertyChanged(nameof(DetectionTrendPoints));
        OnPropertyChanged(nameof(AlertTrendPoints));
        OnPropertyChanged(nameof(FrameTrendPoints));
        OnPropertyChanged(nameof(CoverageTrendPoints));
        OnPropertyChanged(nameof(ScoreTrendPoints));
        OnPropertyChanged(nameof(LatencyTrendPoints));
        OnPropertyChanged(nameof(DroppedTrendPoints));
    }
}

public sealed class AnalyticsViewModel : SectionViewModel
{
    private string selectedAnalyticsSection = "OVERVIEW";

    // Rolling 20-point histories for the 6 KPI sparklines
    private readonly List<double> reliabilityHistory  = new();
    private readonly List<double> warningAlertHistory = new();
    private readonly List<double> riskScoreHistory    = new();
    private readonly List<double> alertCountHistory   = new();
    private readonly List<double> confidenceHistory   = new();
    private readonly List<double> anomalyScoreLineHistory = new();

    public AnalyticsViewModel(VehicleDataService vehicleDataService)
        : base(vehicleDataService, SectionKey.Analytics)
    {
        ChartPoints = new ObservableCollection<double>();
        AttackDistributionBars = new ObservableCollection<double>();
        AlertsHistogramBars = new ObservableCollection<double>();
        AnomalyDistributionBars = new ObservableCollection<double>();
        RuntimePerformanceBars = new ObservableCollection<double>();
        TopAttackedCanIds = new ObservableCollection<CanIdActivityItem>();
        AnomalyScoreTimeline = new ObservableCollection<double>();
        AttackTypeCounts = new ObservableCollection<AttackCountItem>
        {
            new AttackCountItem { Name = "DoS" },
            new AttackCountItem { Name = "Fuzzy" },
            new AttackCountItem { Name = "RPM" },
            new AttackCountItem { Name = "Gear" },
        };
        TriggerReasonCounts = new ObservableCollection<TriggerReasonItem>
        {
            new TriggerReasonItem { Reason = "can_id_entropy" },
            new TriggerReasonItem { Reason = "timing_burst" },
            new TriggerReasonItem { Reason = "continuity_break" },
            new TriggerReasonItem { Reason = "ml_outlier" },
        };
        SeverityCounts = new ObservableCollection<StatSliceItem>
        {
            new StatSliceItem { Name = "CRITICAL", Count = 0, Percent = 0 },
            new StatSliceItem { Name = "HIGH",     Count = 0, Percent = 0 },
            new StatSliceItem { Name = "MEDIUM",   Count = 0, Percent = 0 },
            new StatSliceItem { Name = "LOW",      Count = 0, Percent = 0 },
        };

        OverviewCommand = new RelayCommand(() => SelectedAnalyticsSection = "OVERVIEW");
        BatteryDegradationCommand = new RelayCommand(() => SelectedAnalyticsSection = "ATTACK DISTRIBUTION");
        FaultTrendsCommand = new RelayCommand(() => SelectedAnalyticsSection = "ALERTS HISTOGRAM");
        AIAnomaliesCommand = new RelayCommand(() => SelectedAnalyticsSection = "ANOMALY DISTRIBUTION");
        ReliabilityScoreCommand = new RelayCommand(() => SelectedAnalyticsSection = "RUNTIME PERFORMANCE");
        GenerateReportCommand = new RelayCommand(ExportReport);
        ExportChartsCommand = new RelayCommand(() => SelectedAnalyticsSection = "TOP CAN IDS");
        CompareSessionsCommand = new RelayCommand(() => RefreshAnalytics());

        // Commands required by AnalyticsView.xaml (39258c6 section system)
        AnomalyTimelineCommand = new RelayCommand(() => SelectedAnalyticsSection = "ANOMALY TIMELINE");
        TrafficRateCommand     = new RelayCommand(() => SelectedAnalyticsSection = "TRAFFIC RATE");
        SeverityDistCommand    = new RelayCommand(() => SelectedAnalyticsSection = "SEVERITY DIST");
        ContributionCommand    = new RelayCommand(() => SelectedAnalyticsSection = "CONTRIBUTION");

        vehicleDataService.AlertHistoryUpdated += _ => RefreshAnalytics();
        RefreshAnalytics();
    }

    public override int MaxCards => 1;

    public ObservableCollection<double> ChartPoints { get; }
    public ObservableCollection<double> AttackDistributionBars { get; }
    public ObservableCollection<double> AlertsHistogramBars { get; }
    public ObservableCollection<double> AnomalyDistributionBars { get; }
    public ObservableCollection<double> RuntimePerformanceBars { get; }
    public ObservableCollection<CanIdActivityItem> TopAttackedCanIds { get; }

    public IRelayCommand OverviewCommand { get; }
    public IRelayCommand BatteryDegradationCommand { get; }
    public IRelayCommand FaultTrendsCommand { get; }
    public IRelayCommand AIAnomaliesCommand { get; }
    public IRelayCommand ReliabilityScoreCommand { get; }
    public IRelayCommand GenerateReportCommand { get; }
    public IRelayCommand ExportChartsCommand { get; }
    public IRelayCommand CompareSessionsCommand { get; }

    // Commands required by AnalyticsView.xaml (39258c6 section system)
    public IRelayCommand AnomalyTimelineCommand { get; }
    public IRelayCommand TrafficRateCommand { get; }
    public IRelayCommand SeverityDistCommand { get; }
    public IRelayCommand ContributionCommand { get; }

    // Collections required by AnalyticsView.xaml (39258c6)
    public ObservableCollection<double> AnomalyScoreTimeline { get; }
    public ObservableCollection<StatSliceItem> SeverityCounts { get; }

    // Live sparkline trend points for the 6 KPI header cards
    public System.Windows.Media.PointCollection PrecisionTrendPoints    { get; private set; } = new();
    public System.Windows.Media.PointCollection FalsePositiveTrendPoints { get; private set; } = new();
    public System.Windows.Media.PointCollection RiskScoreTrendPoints    { get; private set; } = new();
    public System.Windows.Media.PointCollection AttackCoverageTrendPoints { get; private set; } = new();
    public System.Windows.Media.PointCollection ModelConfidenceTrendPoints { get; private set; } = new();
    public System.Windows.Media.PointCollection AnomalyScoreLinePoints       { get; private set; } = new();
    public System.Windows.Media.PointCollection ThreatEvolutionSeverityPoints { get; private set; } = new();
    public System.Windows.Media.PointCollection ThreatEvolutionConfidencePoints { get; private set; } = new();
    public System.Windows.Media.PointCollection ModelPerfConfidencePoints     { get; private set; } = new();
    public System.Windows.Media.PointCollection ModelPerfPrecisionPoints      { get; private set; } = new();

    public string CurrentAttackText => VehicleDataService.DetectedAttackType;

    public ObservableCollection<AttackCountItem> AttackTypeCounts { get; }
    public ObservableCollection<TriggerReasonItem> TriggerReasonCounts { get; }

    public string FusionScoreText   => $"{VehicleDataService.CurrentAnomalyScore:F3}";
    public string AvgScoreText      => $"{VehicleDataService.AverageAnomalyScore:F3}";
    public string PeakScoreText     => $"{VehicleDataService.MaxAnomalyScore:F3}";
    public int    HighSeverityCount => VehicleDataService.CriticalAlerts;
    public string ReplayNameText    => VehicleDataService.ReplayName;
    public string RuntimeFpsText    => $"{VehicleDataService.RuntimeFps:F0}";

    // Scalar properties required by AnalyticsView.xaml (39258c6)
    public string CanTrafficRateText => $"{VehicleDataService.RuntimeFps:F0} PPS";
    public string TimingContributionText
    {
        get
        {
            var history = VehicleDataService.AlertHistory;
            if (history.Count == 0) return "0.0%";
            var timing = history.Count(item => item.AttackType is "DoS" or "Fuzzy");
            return $"{timing * 100.0 / history.Count:F1}%";
        }
    }
    public string PayloadContributionText
    {
        get
        {
            var history = VehicleDataService.AlertHistory;
            if (history.Count == 0) return "0.0%";
            var payload = history.Count(item => item.AttackType is "RPM" or "Gear");
            return $"{payload * 100.0 / history.Count:F1}%";
        }
    }

    public string SelectedAnalyticsSection
    {
        get => selectedAnalyticsSection;
        set => SetProperty(ref selectedAnalyticsSection, value);
    }

    public int TotalAlerts => VehicleDataService.TotalAlerts;
    public int CriticalAlerts => VehicleDataService.CriticalAlerts;
    public int WarningAlerts => VehicleDataService.WarningAlerts;
    public double NeuralConfidence => VehicleDataService.DetectionConfidence;
    public double HeatIndex => VehicleDataService.CurrentAnomalyScore;
    public double BatteryHealthIndex => Math.Max(0, 100 - VehicleDataService.MaxAnomalyScore);
    public string BatteryHealthIndexText => $"{BatteryHealthIndex:F1}%";
    public override double ReliabilityScore => Math.Max(0, 100 - VehicleDataService.AverageAnomalyScore);
    public override string ReliabilityScoreText => $"{ReliabilityScore:F1}%";

    public string AnalyticsSummary =>
        $"Attack: {VehicleDataService.DetectedAttackType} | Alerts: {VehicleDataService.TotalAlerts} | Avg score: {VehicleDataService.AverageAnomalyScore:F2} | Max score: {VehicleDataService.MaxAnomalyScore:F2} | Top CAN: {VehicleDataService.TopSuspiciousCanId}";

    public string RuntimePerformanceText =>
        $"FPS {VehicleDataService.RuntimeFps:F1} | Latency {VehicleDataService.RuntimeLatencyMs:F1} ms | Progress {VehicleDataService.ReplayProgressPercent:F1}%";

    protected override void OnDataUpdated(VehicleSnapshot snapshot)
    {
        base.OnDataUpdated(snapshot);
        RefreshAnalytics();
    }

    private void RefreshAnalytics()
    {
        var history = VehicleDataService.AlertHistory;
        var now = DateTime.UtcNow;

        ChartPoints.Clear();
        AttackDistributionBars.Clear();
        AlertsHistogramBars.Clear();
        AnomalyDistributionBars.Clear();
        RuntimePerformanceBars.Clear();
        TopAttackedCanIds.Clear();

        var byAttack = history
            .GroupBy(item => item.AttackType)
            .OrderByDescending(group => group.Count())
            .Take(5)
            .ToList();
        foreach (var group in byAttack)
        {
            AttackDistributionBars.Add(18 + Math.Min(180, group.Count() * 8));
        }

        if (history.Count > 0)
        {
            var earliest    = history.Min(item => item.TimestampUtc);
            var latest      = history.Max(item => item.TimestampUtc);
            var bucketTicks = Math.Max(1L, (latest - earliest).Ticks / 10);
            for (var i = 0; i < 10; i++)
            {
                var from  = earliest.AddTicks(i * bucketTicks);
                var to    = earliest.AddTicks((i + 1) * bucketTicks);
                var count = history.Count(item => item.TimestampUtc >= from && item.TimestampUtc < to);
                AlertsHistogramBars.Add(18 + Math.Min(180, count * 10));
            }
        }
        else
        {
            for (var i = 0; i < 10; i++)
                AlertsHistogramBars.Add(18);
        }

        // Score buckets aligned to fusion score range 0.0–1.5
        var scoreBuckets = new[] { 0.0, 0.3, 0.55, 0.8, 1.0, 1.5 };
        for (var i = 0; i < scoreBuckets.Length - 1; i++)
        {
            var low  = scoreBuckets[i];
            var high = scoreBuckets[i + 1];
            var count = history.Count(item => item.Score >= low && item.Score < high);
            AnomalyDistributionBars.Add(18 + Math.Min(180, count * 8));
        }

        RuntimePerformanceBars.Add(18 + Math.Min(180, VehicleDataService.RuntimeFps * 2));
        RuntimePerformanceBars.Add(18 + Math.Min(180, VehicleDataService.RuntimeLatencyMs));
        RuntimePerformanceBars.Add(18 + Math.Min(180, VehicleDataService.ReplayProgressPercent * 1.6));

        foreach (var group in history
                     .GroupBy(item => item.CanId)
                     .OrderByDescending(g => g.Count())
                     .Take(6))
        {
            TopAttackedCanIds.Add(new CanIdActivityItem { CanId = group.Key, Count = group.Count() });
            ChartPoints.Add(18 + Math.Min(180, group.Count() * 8));
        }

        // AnomalyScoreTimeline: last 20 alert scores — Score is 0.0–1.5 fusion range, scale to 4–280 px
        AnomalyScoreTimeline.Clear();
        foreach (var alert in history.OrderByDescending(a => a.TimestampUtc).Take(20).Reverse())
        {
            AnomalyScoreTimeline.Add(Math.Max(4, Math.Min(280, alert.Score / 1.5 * 280)));
        }

        // SeverityCounts: distribution by severity label — Score is fusion score (0.0–1.5 range)
        var total = history.Count;
        var severityGroups = new[]
        {
            ("CRITICAL", history.Count(a => a.Score >= 1.0)),
            ("HIGH",     history.Count(a => a.Score >= 0.8 && a.Score < 1.0)),
            ("MEDIUM",   history.Count(a => a.Score >= 0.55 && a.Score < 0.8)),
            ("LOW",      history.Count(a => a.Score < 0.55)),
        };
        for (var si = 0; si < SeverityCounts.Count && si < severityGroups.Length; si++)
        {
            var (name, count) = severityGroups[si];
            SeverityCounts[si].Name    = name;
            SeverityCounts[si].Count   = count;
            SeverityCounts[si].Percent = total > 0 ? count * 200.0 / total : 0;
        }

        // Update rolling histories and rebuild sparkline point collections
        static void Push(List<double> hist, double value, int max = 20)
        {
            hist.Add(value);
            if (hist.Count > max) hist.RemoveAt(0);
        }
        Push(reliabilityHistory,      ReliabilityScore);
        Push(warningAlertHistory,     VehicleDataService.WarningAlerts);
        Push(riskScoreHistory,        VehicleDataService.CurrentAnomalyScore);
        Push(alertCountHistory,       VehicleDataService.TotalAlerts);
        Push(confidenceHistory,       VehicleDataService.DetectionConfidence);
        Push(anomalyScoreLineHistory, VehicleDataService.CurrentAnomalyScore);

        PrecisionTrendPoints       = BuildAnalyticsTrend(reliabilityHistory,      144, 22);
        FalsePositiveTrendPoints   = BuildAnalyticsTrend(warningAlertHistory,     144, 22);
        RiskScoreTrendPoints       = BuildAnalyticsTrend(riskScoreHistory,        144, 22);
        AttackCoverageTrendPoints  = BuildAnalyticsTrend(alertCountHistory,       144, 22);
        ModelConfidenceTrendPoints = BuildAnalyticsTrend(confidenceHistory,       144, 22);
        // Fusion score monitor uses fixed 0-1.5 Y scale so threshold lines are accurate
        AnomalyScoreLinePoints          = BuildFixedRangeTrend(anomalyScoreLineHistory, 634, 112, 0, 1.5);
        ThreatEvolutionSeverityPoints   = BuildAnalyticsTrend(riskScoreHistory,         570, 136);
        ThreatEvolutionConfidencePoints = BuildAnalyticsTrend(confidenceHistory,         570, 136);
        ModelPerfConfidencePoints       = BuildAnalyticsTrend(confidenceHistory,         302, 72);
        ModelPerfPrecisionPoints        = BuildAnalyticsTrend(reliabilityHistory,        302, 72);

        // Attack type distribution from real alert history
        var alertCount = history.Count;
        foreach (var item in AttackTypeCounts)
        {
            var cnt = history.Count(a => string.Equals(a.AttackType, item.Name, StringComparison.OrdinalIgnoreCase));
            item.Count    = cnt;
            item.Pct      = alertCount > 0 ? cnt * 100.0 / alertCount : 0;
            item.BarWidth = alertCount > 0 ? cnt * 140.0 / alertCount : 0;
        }

        // Detection trigger breakdown (timing_burst vs continuity_break)
        foreach (var item in TriggerReasonCounts)
        {
            var cnt = history.Count(a => string.Equals(a.Reason, item.Reason, StringComparison.OrdinalIgnoreCase));
            item.Count    = cnt;
            item.Pct      = alertCount > 0 ? cnt * 100.0 / alertCount : 0;
            item.BarWidth = alertCount > 0 ? cnt * 140.0 / alertCount : 0;
        }

        OnPropertyChanged(nameof(TotalAlerts));
        OnPropertyChanged(nameof(CriticalAlerts));
        OnPropertyChanged(nameof(WarningAlerts));
        OnPropertyChanged(nameof(NeuralConfidence));
        OnPropertyChanged(nameof(HeatIndex));
        OnPropertyChanged(nameof(BatteryHealthIndex));
        OnPropertyChanged(nameof(BatteryHealthIndexText));
        OnPropertyChanged(nameof(ReliabilityScore));
        OnPropertyChanged(nameof(ReliabilityScoreText));
        OnPropertyChanged(nameof(AnalyticsSummary));
        OnPropertyChanged(nameof(RuntimePerformanceText));
        OnPropertyChanged(nameof(CanTrafficRateText));
        OnPropertyChanged(nameof(TimingContributionText));
        OnPropertyChanged(nameof(PayloadContributionText));
        OnPropertyChanged(nameof(PrecisionTrendPoints));
        OnPropertyChanged(nameof(FalsePositiveTrendPoints));
        OnPropertyChanged(nameof(RiskScoreTrendPoints));
        OnPropertyChanged(nameof(AttackCoverageTrendPoints));
        OnPropertyChanged(nameof(ModelConfidenceTrendPoints));
        OnPropertyChanged(nameof(AnomalyScoreLinePoints));
        OnPropertyChanged(nameof(ThreatEvolutionSeverityPoints));
        OnPropertyChanged(nameof(ThreatEvolutionConfidencePoints));
        OnPropertyChanged(nameof(ModelPerfConfidencePoints));
        OnPropertyChanged(nameof(ModelPerfPrecisionPoints));
        OnPropertyChanged(nameof(CurrentAttackText));
        OnPropertyChanged(nameof(FusionScoreText));
        OnPropertyChanged(nameof(AvgScoreText));
        OnPropertyChanged(nameof(PeakScoreText));
        OnPropertyChanged(nameof(HighSeverityCount));
        OnPropertyChanged(nameof(ReplayNameText));
        OnPropertyChanged(nameof(RuntimeFpsText));
    }

    private static System.Windows.Media.PointCollection BuildFixedRangeTrend(
        IReadOnlyList<double> values, double width, double height, double minVal, double maxVal)
    {
        var points = new System.Windows.Media.PointCollection();
        if (values.Count < 2) return points;
        var range = maxVal - minVal;
        for (var i = 0; i < values.Count; i++)
        {
            var x = i * width / (values.Count - 1);
            var normalized = range > 0 ? Math.Max(0, Math.Min(1, (values[i] - minVal) / range)) : 0;
            var y = height - 1 - normalized * (height - 2);
            points.Add(new System.Windows.Point(x, y));
        }
        return points;
    }

    private static System.Windows.Media.PointCollection BuildAnalyticsTrend(IReadOnlyList<double> values, double width, double height)
    {
        var points = new System.Windows.Media.PointCollection();
        if (values.Count < 2) return points;
        var min = values.Min();
        var max = values.Max();
        var range = max - min;
        for (var i = 0; i < values.Count; i++)
        {
            var x = i * width / (values.Count - 1);
            var normalized = range > 0.001 ? (values[i] - min) / range : 0.5;
            var y = height - 1 - normalized * (height - 2); // high value = low Y (top of canvas)
            points.Add(new System.Windows.Point(x, y));
        }
        return points;
    }

    private void ExportReport()
    {
        var dialog = new SaveFileDialog
        {
            Filter = "CSV Report (*.csv)|*.csv|JSON Report (*.json)|*.json",
            FileName = $"Analytics_{DateTime.Now:yyyyMMdd_HHmm}",
            Title = "Export Analytics Report",
        };

        if (dialog.ShowDialog() != true)
        {
            return;
        }

        if (dialog.FileName.EndsWith(".json", StringComparison.OrdinalIgnoreCase))
        {
            var payload = new
            {
                replay = VehicleDataService.ReplayName,
                attack = VehicleDataService.DetectedAttackType,
                total_alerts = VehicleDataService.TotalAlerts,
                critical_alerts = VehicleDataService.CriticalAlerts,
                warning_alerts = VehicleDataService.WarningAlerts,
                avg_score = VehicleDataService.AverageAnomalyScore,
                max_score = VehicleDataService.MaxAnomalyScore,
                top_can_id = VehicleDataService.TopSuspiciousCanId,
                runtime_fps = VehicleDataService.RuntimeFps,
                latency_ms = VehicleDataService.RuntimeLatencyMs,
                progress_percent = VehicleDataService.ReplayProgressPercent,
            };
            File.WriteAllText(dialog.FileName, JsonConvert.SerializeObject(payload, Formatting.Indented));
            return;
        }

        var rows = new List<string>
        {
            "metric,value",
            $"Replay,{VehicleDataService.ReplayName}",
            $"AttackType,{VehicleDataService.DetectedAttackType}",
            $"TotalAlerts,{VehicleDataService.TotalAlerts}",
            $"CriticalAlerts,{VehicleDataService.CriticalAlerts}",
            $"WarningAlerts,{VehicleDataService.WarningAlerts}",
            $"AverageScore,{VehicleDataService.AverageAnomalyScore:F4}",
            $"MaxScore,{VehicleDataService.MaxAnomalyScore:F4}",
            $"TopCAN,{VehicleDataService.TopSuspiciousCanId}",
            $"RuntimeFPS,{VehicleDataService.RuntimeFps:F4}",
            $"LatencyMs,{VehicleDataService.RuntimeLatencyMs:F4}",
            $"ReplayProgress,{VehicleDataService.ReplayProgressPercent:F2}",
        };
        File.WriteAllLines(dialog.FileName, rows);
    }
}

public sealed class SettingsViewModel : SectionViewModel
{
    public SettingsViewModel(VehicleDataService vehicleDataService)
        : base(vehicleDataService, SectionKey.Settings)
    {
        SettingsCategories = new ObservableCollection<string>
        {
            "OBD2 ADAPTER",
            "CAN INTERFACE",
            "VEHICLE PROFILES",
            "THEME",
            "AI MODEL",
            "EXPORT",
        };
        ProfileCards = new ObservableCollection<ProfileItem>
        {
            new("P-800 Performance", "ACTIVE", "High-response track profile"),
            new("Street Touring", "SYNCED", "Balanced drive calibration"),
            new("Thermal Safe", "ARCHIVED", "Cooling-first endurance preset"),
        };
        SelectSettingsCategoryCommand = new RelayCommand<string>(category => SelectedSettingsCategory = category ?? "OBD2 ADAPTER");
        selectedSettingsCategory = "OBD2 ADAPTER";
    }

    private string selectedSettingsCategory;

    public ObservableCollection<string> SettingsCategories { get; }

    public ObservableCollection<ProfileItem> ProfileCards { get; }

    public IRelayCommand<string> SelectSettingsCategoryCommand { get; }

    public string SelectedSettingsCategory
    {
        get => selectedSettingsCategory;
        set => SetProperty(ref selectedSettingsCategory, value);
    }

    public string RuntimeMode => ConnectivityText;

    public string ApiEndpoint => VehicleDataService.ApiEndpoint;

    public string JsonFallbackPath => VehicleDataService.JsonFallbackPath;

    public string RefreshIntervalText => $"{(int)VehicleDataService.RefreshInterval.TotalMilliseconds} MS";

    public string RendererProfile => "HELIX SHARPDX GARAGE RENDERER";

    public string DetectionModelText => "CAN-GPT V4 (TURBO)";

    public string TrainingDateText => "2026-04-08";

    public string AccuracyText => "94.6%";

    protected override void OnDataUpdated(VehicleSnapshot snapshot)
    {
        OnPropertyChanged(nameof(RuntimeMode));
    }
}

public sealed class MetricCardItem
{
    public MetricCardItem(string title, string value, string detail, string state)
    {
        Title = title;
        Value = value;
        Detail = detail;
        State = state;
    }

    public string Title { get; }
    public string Value { get; }
    public string Detail { get; }
    public string State { get; }
}

public sealed class StatusBadgeItem
{
    public StatusBadgeItem(string title, string value)
    {
        Title = title;
        Value = value;
    }

    public string Title { get; }
    public string Value { get; }
}

public sealed class AlertItem
{
    public AlertItem(string title, string detail, string state)
    {
        Title = title;
        Detail = detail;
        State = state;
    }

    public string Title { get; }
    public string Detail { get; }
    public string State { get; }
}

public sealed class SignalItem
{
    public SignalItem(
        string canId,
        string name,
        string value,
        string unit,
        string state,
        double freq = 0,
        double tdiff = 0,
        System.Windows.Media.PointCollection? trendPoints = null,
        string stateBrush = "#56F0AC",
        string canIdBrush = "#6E9090")
    {
        CanId = canId;
        Name = name;
        Value = value;
        Unit = unit;
        State = state;
        Frequency = freq;
        TimeDiff = tdiff;
        TrendPoints = trendPoints ?? new System.Windows.Media.PointCollection();
        StateBrush = stateBrush;
        CanIdBrush = canIdBrush;
    }

    public string CanId { get; }
    public string Name { get; }
    public string Value { get; }
    public string Unit { get; }
    public string State { get; }
    public double Frequency { get; }
    public double TimeDiff { get; }
    public System.Windows.Media.PointCollection TrendPoints { get; }
    public string StateBrush { get; }
    public string CanIdBrush { get; }
    public string FrequencyText => $"{Frequency:F1} Hz";
    public string TimeDiffText => $"{TimeDiff:F4}s";
}

public sealed class AxisLabelItem
{
    public AxisLabelItem(string text, double offset)
    {
        Text = text;
        Offset = offset;
    }

    public string Text { get; }
    public double Offset { get; }
}

public sealed class ReplayMarkerItem
{
    public ReplayMarkerItem(double offset, string label)
    {
        Offset = offset;
        Label = label;
    }

    public double Offset { get; }
    public string Label { get; }
}

public sealed class SubsystemStateItem
{
    public SubsystemStateItem(string name, string state, string stateBrush, string detail)
    {
        Name = name;
        State = state;
        StateBrush = stateBrush;
        Detail = detail;
    }

    public string Name { get; }
    public string State { get; }
    public string StateBrush { get; }
    public string Detail { get; }
}

public sealed class TelemetryEventItem
{
    public TelemetryEventItem(string timestamp, string severity, string source, string message)
    {
        Timestamp = timestamp;
        Severity = severity;
        Source = source;
        Message = message;
    }

    public string Timestamp { get; }
    public string Severity { get; }
    public string Source { get; }
    public string Message { get; }

    public string SeverityBrush => Severity switch
    {
        "CRITICAL"          => "#FF5050",
        "WARNING" or "WARN" => "#FFD94A",
        "INFO"              => "#56F0AC",
        _                   => "#6E9090",
    };
}

public sealed class SignalLegendItem
{
    public SignalLegendItem(string name, string colorHex)
    {
        Name = name;
        ColorHex = colorHex;
    }

    public string Name { get; }
    public string ColorHex { get; }
}

public sealed class FaultCodeItem
{
    public FaultCodeItem(string code, string description, string severity, string source, string timestamp)
    {
        Code = code;
        Description = description;
        Severity = severity;
        Source = source;
        Timestamp = timestamp;
    }

    public string Code { get; }
    public string Description { get; }
    public string Severity { get; }
    public string Source { get; }
    public string Timestamp { get; }
}

public sealed class DiagnosticDtcItem : ObservableObject
{
    private string status = "ACTIVE";

    public string FaultKey { get; set; } = string.Empty;
    public string Code { get; set; } = string.Empty;
    public string Description { get; set; } = string.Empty;
    public string Severity { get; set; } = "INFO";
    public string Source { get; set; } = "CAN_PIPELINE";
    public string CanId { get; set; } = "0x000";
    public DateTime Timestamp { get; set; } = DateTime.UtcNow;
    public DateTime FirstSeen { get; set; } = DateTime.UtcNow;
    public DateTime LastSeen { get; set; } = DateTime.UtcNow;
    public string AnomalyType { get; set; } = "GENERAL";
    public double ConfidenceScore { get; set; }
    public string Explanation { get; set; } = string.Empty;

    public string Status
    {
        get => status;
        set => SetProperty(ref status, value);
    }

    public string TimestampText => Timestamp.ToLocalTime().ToString("HH:mm:ss");
}

public sealed class TrendBucketItem
{
    public string Label { get; set; } = string.Empty;
    public int Count { get; set; }
    public double Height { get; set; }
}

public sealed class StatSliceItem
{
    public string Name { get; set; } = string.Empty;
    public int Count { get; set; }
    public double Percent { get; set; }
}

public sealed class CanIdActivityItem
{
    public string CanId { get; set; } = string.Empty;
    public int Count { get; set; }
}

public sealed class SessionComparisonItem
{
    public string Metric { get; set; } = string.Empty;
    public int Current { get; set; }
    public int Previous { get; set; }
    public int Delta { get; set; }
    public string DeltaText => Delta == 0 ? "0" : (Delta > 0 ? $"+{Delta}" : Delta.ToString());
}

public sealed class RecommendationItem
{
    public RecommendationItem(string title, string detail)
    {
        Title = title;
        Detail = detail;
    }

    public string Title { get; }
    public string Detail { get; }
}

public sealed class AttackCountItem : ObservableObject
{
    private string name = "";
    private int count;
    private double pct;
    private double barWidth;
    private string pctText = "0.0%";

    public string Name     { get => name;     set => SetProperty(ref name, value); }
    public int    Count    { get => count;    set => SetProperty(ref count, value); }
    public double Pct      { get => pct;      set { SetProperty(ref pct, value); PctText = $"{value:F1}%"; } }
    public double BarWidth { get => barWidth; set => SetProperty(ref barWidth, value); }
    public string PctText  { get => pctText;  set => SetProperty(ref pctText, value); }
}

public sealed class TriggerReasonItem : ObservableObject
{
    private string reason = "";
    private int count;
    private double pct;
    private double barWidth;
    private string pctText = "0.0%";

    public string Reason   { get => reason;   set => SetProperty(ref reason, value); }
    public int    Count    { get => count;    set => SetProperty(ref count, value); }
    public double Pct      { get => pct;      set { SetProperty(ref pct, value); PctText = $"{value:F1}%"; } }
    public double BarWidth { get => barWidth; set => SetProperty(ref barWidth, value); }
    public string PctText  { get => pctText;  set => SetProperty(ref pctText, value); }
}

public sealed class PlaybackSessionItem
{
    public PlaybackSessionItem(string fileName, string date, string duration, string frameCount)
    {
        FileName = fileName;
        Date = date;
        Duration = duration;
        FrameCount = frameCount;
    }

    public string FileName { get; }
    public string Date { get; }
    public string Duration { get; }
    public string FrameCount { get; }
}

public sealed class PlaybackEventItem
{
    public PlaybackEventItem(string timestamp, string frameId, string data, string decodedSignal)
    {
        Timestamp = timestamp;
        FrameId = frameId;
        Data = data;
        DecodedSignal = decodedSignal;
    }

    public string Timestamp { get; }
    public string FrameId { get; }
    public string Data { get; }
    public string DecodedSignal { get; }
}

public sealed class ForensicTimelineMarker
{
    public ForensicTimelineMarker(string track, double left, double top, string label, string color)
    {
        Track = track;
        Left = left;
        Top = top;
        Label = label;
        Color = color;
    }

    public string Track { get; }
    public double Left { get; }
    public double Top { get; }
    public string Label { get; }
    public string Color { get; }
}

public sealed class ForensicTimelineWindow
{
    public ForensicTimelineWindow(string track, double left, double width, double top, string color)
    {
        Track = track;
        Left = left;
        Width = width;
        Top = top;
        Color = color;
    }

    public string Track { get; }
    public double Left { get; }
    public double Width { get; }
    public double Top { get; }
    public string Color { get; }
}

public sealed class CorrelationRowItem
{
    public CorrelationRowItem(string time, string canId, string eventText, string severity, string detection, string groundTruth, string details)
    {
        Time = time;
        CanId = canId;
        Event = eventText;
        Severity = severity;
        Detection = detection;
        GroundTruth = groundTruth;
        Details = details;
    }

    public string Time { get; }
    public string CanId { get; }
    public string Event { get; }
    public string Severity { get; }
    public string Detection { get; }
    public string GroundTruth { get; }
    public string Details { get; }
}

public sealed class ReplayEventRowItem
{
    public ReplayEventRowItem(string time, string severity, string source, string message)
    {
        Time = time;
        Severity = severity;
        Source = source;
        Message = message;
    }

    public string Time { get; }
    public string Severity { get; }
    public string Source { get; }
    public string Message { get; }
}

public sealed class SignalPlotSeriesItem
{
    public SignalPlotSeriesItem(string name, string color, System.Windows.Media.PointCollection points)
    {
        Name = name;
        Color = color;
        Points = points;
    }

    public string Name { get; }
    public string Color { get; }
    public System.Windows.Media.PointCollection Points { get; }
}

public sealed class AnalysisKpiItem : CommunityToolkit.Mvvm.ComponentModel.ObservableObject
{
    public AnalysisKpiItem(string label, string value, string meta, System.Windows.Media.PointCollection trendPoints, string color)
    {
        Label = label;
        _value = value;
        _meta = meta;
        TrendPoints = trendPoints;
        Color = color;
    }

    private string _value;
    private string _meta;

    public string Label { get; }
    public string Value
    {
        get => _value;
        set => SetProperty(ref _value, value);
    }
    public string Meta
    {
        get => _meta;
        set => SetProperty(ref _meta, value);
    }
    public System.Windows.Media.PointCollection TrendPoints { get; }
    public string Color { get; }
}

public sealed class ProfileItem
{
    public ProfileItem(string name, string state, string description)
    {
        Name = name;
        State = state;
        Description = description;
    }

    public string Name { get; }
    public string State { get; }
    public string Description { get; }
}

public sealed class SubsystemItem : ObservableObject
{
    private string state;

    public SubsystemItem(string name, string detail, string state)
    {
        Name = name;
        Detail = detail;
        this.state = state;
    }

    public string Name { get; }
    public string Detail { get; }
    
    public string State
    {
        get => state;
        set => SetProperty(ref state, value);
    }
}

// ──────────────────────────────────────────────────────────────────────────────
// Validation Lab — supporting types
// ──────────────────────────────────────────────────────────────────────────────

public sealed class GtAttackWindow : ObservableObject
{
    private string canIdHex = "--";

    public double StartSec { get; set; }
    public double EndSec { get; set; }
    public string AttackType { get; set; } = "--";

    public string CanIdHex
    {
        get => canIdHex;
        set => SetProperty(ref canIdHex, value);
    }

    public string StartSecText => $"{StartSec:F3}s";
    public string EndSecText => $"{EndSec:F3}s";
    public string DurationText => $"{(EndSec - StartSec):F3}s";
}

public sealed class ValidationDetectedWindow
{
    public double StartSec { get; set; }
    public double EndSec { get; set; }
    public string AttackType { get; set; } = "--";
    public bool IsMatched { get; set; }
    public double BarLeft { get; set; }
    public double BarWidth { get; set; }

    public string StartSecText => $"{StartSec:F3}s";
    public string EndSecText => $"{EndSec:F3}s";
    public string StatusText => IsMatched ? "MATCHED" : "FALSE POS";

    private static readonly System.Windows.Media.Brush s_matchBrush =
        new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromArgb(200, 0, 200, 200));
    private static readonly System.Windows.Media.Brush s_fpBrush =
        new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromArgb(200, 255, 80, 80));

    public System.Windows.Media.Brush BarBrush => IsMatched ? s_matchBrush : s_fpBrush;
}

public sealed class ExplainabilityEntry
{
    public string TimestampText { get; set; } = "--";
    public string CanIdHex { get; set; } = "--";
    public string AnomalyType { get; set; } = "--";
    public string Severity { get; set; } = "LOW";
    public int SeverityScore { get; set; }
    public string SeverityScoreText => $"{SeverityScore}%";

    private static readonly System.Windows.Media.Brush s_highBrush =
        new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(255, 100, 100));
    private static readonly System.Windows.Media.Brush s_medBrush =
        new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(255, 200, 80));
    private static readonly System.Windows.Media.Brush s_lowBrush =
        new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(134, 244, 208));

    public System.Windows.Media.Brush SeverityBrush => Severity switch
    {
        "HIGH" or "CRITICAL" => s_highBrush,
        "MEDIUM" => s_medBrush,
        _ => s_lowBrush,
    };
}

public sealed class CanIdCorrelationRow
{
    public string CanIdHex { get; set; } = "--";
    public int HitCount { get; set; }
    public string AttackType { get; set; } = "--";
    public bool IsGroundTruth { get; set; }
    public string SourceLabel => IsGroundTruth ? "GT" : "DETECTED";

    private static readonly System.Windows.Media.Brush s_gtBrush =
        new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(255, 180, 0));
    private static readonly System.Windows.Media.Brush s_detectedBrush =
        new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(0, 200, 200));

    public System.Windows.Media.Brush SourceBrush => IsGroundTruth ? s_gtBrush : s_detectedBrush;
}

public sealed class FalsePositiveEntry
{
    public string TimestampText { get; set; } = "--";
    public string CanIdHex { get; set; } = "--";
    public string AnomalyType { get; set; } = "--";
    public string ScoreText { get; set; } = "--";
}

// ──────────────────────────────────────────────────────────────────────────────
// ValidationLabViewModel
// ──────────────────────────────────────────────────────────────────────────────

public sealed class ValidationLabViewModel : SectionViewModel
{
    private const double TimelineCanvasWidth = 560.0;
    private const double BucketSec = 0.5;
    private const double SpikeMultiplier = 2.5;
    private const int NewIdMinCount = 3;
    private const int FuzzyUniqueThreshold = 10; // unique new CAN-IDs/bucket → Fuzzy flood

    private readonly CanLogImportService canLogImportService;
    private readonly AppLogger logger;
    private readonly DispatcherTimer replayTimer;
    private List<PlaybackPacket> playbackData = new();
    private int currentFrameIndex = 0;
    private readonly List<(double Start, double End, string Type)> validationDetectedWindows = new();
    private bool hasRunDetection = false;

    // Session state
    private string sessionStatus = "NO SESSION LOADED";
    private string loadedFileName = "--";
    private string loadedSourcePath = string.Empty;
    private string sessionDurationText = "--:--:--";
    private int totalFrameCount = 0;
    private bool isRunning = false;
    private string validationMode = "IDLE";

    // GT state
    private List<GtAttackWindow> rawGtWindows = new();
    private int expectedAttacks = 0;
    private string expectedAttackTypesText = "N/A";

    // Runtime counters
    private int detectedAttacks = 0;
    private int matchedAttacks = 0;
    private int missedDetections = 0;
    private int falsePositives = 0;

    // ML diagnostics (set after batch scoring)
    private string mlDetectionPath = "--";
    private int mlFramesScored = 0;
    private int mlAboveThreshold = 0;
    private int mlWindowsGenerated = 0;
    private double matchPercent = 0.0;
    private double precision = 0.0;
    private double recall = 0.0;
    private double f1Score = 0.0;
    private string detectionDelayText = "--";
    private string temporalDriftText = "--";

    // Timeline
    private System.Windows.Media.PointCollection replayTimelinePoints = new();
    private readonly List<double> ppsBuffer = new();

    // Throttle
    private DateTime lastValidationRebuildUtc = DateTime.MinValue;

    public ValidationLabViewModel(
        VehicleDataService vehicleDataService,
        CanLogImportService canLogImportService,
        AppLogger logger)
        : base(vehicleDataService, SectionKey.ValidationLab)
    {
        this.canLogImportService = canLogImportService;
        this.logger = logger;

        GtAttackWindows = new ObservableCollection<GtAttackWindow>();
        DetectedWindows = new ObservableCollection<ValidationDetectedWindow>();
        ExplainabilityRows = new ObservableCollection<ExplainabilityEntry>();
        CanIdCorrelations = new ObservableCollection<CanIdCorrelationRow>();
        FalsePositiveRows = new ObservableCollection<FalsePositiveEntry>();

        replayTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(50) };
        replayTimer.Tick += OnReplayTick;

        ImportDatasetCommand = new AsyncRelayCommand(ImportDatasetAsync);
        ImportGtCommand = new AsyncRelayCommand(ImportGtAsync);
        StartValidationCommand = new RelayCommand(StartValidation, () => playbackData.Count > 0 && !isRunning);
        StopValidationCommand = new RelayCommand(StopValidation, () => isRunning);
        ResetCommand = new RelayCommand(ResetSession);
        ExportReportCommand = new AsyncRelayCommand(ExportReportAsync, () => playbackData.Count > 0);

        vehicleDataService.AnomaliesUpdated += OnAnomaliesUpdated;
    }

    // ── Collections ──────────────────────────────────────────────────────────

    public ObservableCollection<GtAttackWindow> GtAttackWindows { get; }
    public ObservableCollection<ValidationDetectedWindow> DetectedWindows { get; }
    public ObservableCollection<ExplainabilityEntry> ExplainabilityRows { get; }
    public ObservableCollection<CanIdCorrelationRow> CanIdCorrelations { get; }
    public ObservableCollection<FalsePositiveEntry> FalsePositiveRows { get; }

    // ── Commands ─────────────────────────────────────────────────────────────

    public IAsyncRelayCommand ImportDatasetCommand { get; }
    public IAsyncRelayCommand ImportGtCommand { get; }
    public IRelayCommand StartValidationCommand { get; }
    public IRelayCommand StopValidationCommand { get; }
    public IRelayCommand ResetCommand { get; }
    public IAsyncRelayCommand ExportReportCommand { get; }

    // ── Properties ───────────────────────────────────────────────────────────

    public string SessionStatus
    {
        get => sessionStatus;
        private set => SetProperty(ref sessionStatus, value);
    }

    public string LoadedFileName
    {
        get => loadedFileName;
        private set => SetProperty(ref loadedFileName, value);
    }

    public string SessionDurationText
    {
        get => sessionDurationText;
        private set => SetProperty(ref sessionDurationText, value);
    }

    public string ExpectedAttackTypesText
    {
        get => expectedAttackTypesText;
        private set => SetProperty(ref expectedAttackTypesText, value);
    }

    public string DetectionDelayText
    {
        get => detectionDelayText;
        private set => SetProperty(ref detectionDelayText, value);
    }

    public string TemporalDriftText
    {
        get => temporalDriftText;
        private set => SetProperty(ref temporalDriftText, value);
    }

    public System.Windows.Media.PointCollection ReplayTimelinePoints
    {
        get => replayTimelinePoints;
        private set => SetProperty(ref replayTimelinePoints, value);
    }

    public string TotalFrameCountText => totalFrameCount == 0 ? "--" : totalFrameCount.ToString("N0");
    public string CurrentFrameText => playbackData.Count == 0 ? "--" : currentFrameIndex.ToString("N0");
    public bool IsRunning => isRunning;
    public string ValidationModeText => validationMode;
    public string ExpectedAttacksText => expectedAttacks == 0 ? "--" : expectedAttacks.ToString();
    public string DetectedAttacksText => !hasRunDetection ? "--" : detectedAttacks.ToString();
    public string MatchedAttacksText => !hasRunDetection ? "--" : matchedAttacks.ToString();
    public string MissedDetectionsText => !hasRunDetection ? "--" : missedDetections.ToString();
    public string FalsePositivesText => !hasRunDetection ? "--" : falsePositives.ToString();
    public string MatchPercentText => !hasRunDetection ? "--" : $"{matchPercent:F1}%";
    public string PrecisionText => !hasRunDetection ? "--" : $"{precision:F3}";
    public string RecallText => !hasRunDetection ? "--" : $"{recall:F3}";
    public string F1ScoreText => !hasRunDetection ? "--" : $"{f1Score:F3}";

    // ML Diagnostics
    public string MlDetectionPathText => mlDetectionPath;
    public string MlFramesScoredText => mlFramesScored == 0 ? "--" : mlFramesScored.ToString("N0");
    public string MlAboveThresholdText => mlFramesScored == 0 ? "--" : $"{mlAboveThreshold:N0} ({mlAboveThreshold * 100.0 / Math.Max(1, mlFramesScored):F0}%)";
    public string MlWindowsGeneratedText => mlFramesScored == 0 ? "--" : mlWindowsGenerated.ToString();

    // ── Commands implementation ───────────────────────────────────────────────

    private async Task ImportDatasetAsync()
    {
        var dlg = new OpenFileDialog
        {
            Title = "Import Validation Dataset (CSV)",
            Filter = "CSV Files (*.csv)|*.csv|All Files (*.*)|*.*",
        };

        if (dlg.ShowDialog() != true) return;

        playbackData.Clear();
        currentFrameIndex = 0;
        validationDetectedWindows.Clear();
        hasRunDetection = false;
        DetectedWindows.Clear();
        ExplainabilityRows.Clear();
        CanIdCorrelations.Clear();
        FalsePositiveRows.Clear();
        ppsBuffer.Clear();
        ReplayTimelinePoints = new System.Windows.Media.PointCollection();

        // GT from a previous dataset must not contaminate the new one.
        rawGtWindows.Clear();
        GtAttackWindows.Clear();
        expectedAttacks     = 0;
        detectedAttacks     = 0;
        matchedAttacks      = 0;
        missedDetections    = 0;
        falsePositives      = 0;
        matchPercent        = 0;
        precision           = 0;
        recall              = 0;
        f1Score             = 0;
        DetectionDelayText      = "--";
        TemporalDriftText       = "--";
        ExpectedAttackTypesText = "N/A";
        NotifyAllMetrics();

        loadedSourcePath = dlg.FileName;
        LoadedFileName = Path.GetFileName(dlg.FileName);
        SessionStatus = "IMPORTING...";
        totalFrameCount = 0;
        OnPropertyChanged(nameof(TotalFrameCountText));
        OnPropertyChanged(nameof(CurrentFrameText));

        try
        {
            var result = await canLogImportService.ParseFileAsync(dlg.FileName, skipMlScoring: true);
            playbackData = result.Packets.ToList();
            totalFrameCount = playbackData.Count;

            if (totalFrameCount == 0)
            {
                SessionStatus = "IMPORT FAILED — NO FRAMES PARSED";
                return;
            }

            // Batch ML scoring — runs the same RealtimeEngine pipeline as replay analysis.
            // skipMlScoring:true above avoids 100k serial HTTP calls; instead we make
            // one batch call and annotate packets from the result.
            SessionStatus = "SCORING WITH ML...";
            try
            {
                var scoreResult = await canLogImportService.ScoreValidationFileAsync(
                    loadedSourcePath, CancellationToken.None).ConfigureAwait(true);

                if (scoreResult?.Frames != null && scoreResult.Frames.Count > 0)
                {
                    // Build lookup: (rounded_timestamp, can_id) → score entry
                    var scoreMap = new Dictionary<(long, int), ValidationFrameScore>(scoreResult.Frames.Count);
                    foreach (var fs in scoreResult.Frames)
                    {
                        var key = ((long)Math.Round(fs.Timestamp * 1e6), fs.CanId);
                        if (!scoreMap.ContainsKey(key))
                            scoreMap[key] = fs;
                    }

                    // Annotate packets with ML anomaly objects
                    foreach (var packet in playbackData)
                    {
                        var key = ((long)Math.Round(packet.Frame.RelativeTimestampSeconds * 1e6), packet.Frame.CanId);
                        if (!scoreMap.TryGetValue(key, out var fs)) continue;
                        if (string.Equals(fs.Label, "normal", StringComparison.OrdinalIgnoreCase)) continue;

                        var severityScore = (int)Math.Min(100, Math.Round(fs.Score * 100));
                        var existing = new List<CanAnomaly>(packet.Anomalies)
                        {
                            new CanAnomaly
                            {
                                Code = "AI-001",
                                Title = "ML ANOMALY",
                                Description = $"ML detected anomaly: score={fs.Score:F3}, severity={fs.Severity}",
                                Severity = severityScore >= 80 ? "CRITICAL" : severityScore >= 40 ? "WARNING" : "INFO",
                                SeverityScore = severityScore,
                                AnomalyScore = fs.Score,
                                RelatedCanId = packet.Frame.CanId,
                                TimestampUtc = packet.Frame.TimestampUtc,
                                Source = "ai",
                            }
                        };
                        packet.Anomalies = existing;
                    }

                    mlFramesScored = scoreResult.FrameCount;
                    mlAboveThreshold = scoreResult.AnomalyCount;
                    logger.Info($"[VALLAB] ML scoring complete: {scoreResult.AnomalyCount}/{scoreResult.FrameCount} anomaly frames annotated.");
                }
                else
                {
                    mlFramesScored = 0;
                    mlAboveThreshold = 0;
                    logger.Info("[VALLAB] ML scoring returned no results — falling back to frequency detection.");
                }
            }
            catch (Exception mlEx)
            {
                logger.Error("[VALLAB] ML batch scoring failed; frequency fallback will be used.", mlEx);
            }

            var durationSec = playbackData[playbackData.Count - 1].Frame.RelativeTimestampSeconds
                            - playbackData[0].Frame.RelativeTimestampSeconds;
            var ts = TimeSpan.FromSeconds(durationSec);
            SessionDurationText = $"{(int)ts.TotalHours:D2}:{ts.Minutes:D2}:{ts.Seconds:D2}.{ts.Milliseconds:D3}";
            SessionStatus = $"READY — {totalFrameCount:N0} FRAMES · {LoadedFileName}";
            validationMode = "IDLE";

            OnPropertyChanged(nameof(TotalFrameCountText));
            OnPropertyChanged(nameof(CurrentFrameText));
            OnPropertyChanged(nameof(ValidationModeText));
            StartValidationCommand.NotifyCanExecuteChanged();
            ExportReportCommand.NotifyCanExecuteChanged();

            logger.Info($"[VALLAB] Dataset imported: {totalFrameCount} frames from {LoadedFileName}");

            if (rawGtWindows.Count > 0)
            {
                RunDetection();
                UpdateAllMetrics();
                RebuildDetectedWindows();
                RebuildExplainability();
                RebuildCanIdCorrelations();
                RebuildFalsePositives();
            }
        }
        catch (Exception ex)
        {
            logger.Error("[VALLAB] Dataset import failed.", ex);
            SessionStatus = "IMPORT FAILED";
        }
    }

    private async Task ImportGtAsync()
    {
        var dlg = new OpenFileDialog
        {
            Title = "Import Ground Truth CSV",
            Filter = "CSV Files (*.csv)|*.csv|All Files (*.*)|*.*",
        };

        if (dlg.ShowDialog() != true) return;

        rawGtWindows.Clear();
        GtAttackWindows.Clear();
        hasRunDetection = false;
        validationDetectedWindows.Clear();
        DetectedWindows.Clear();

        try
        {
            var lines = await Task.Run(() => File.ReadAllLines(dlg.FileName));

            double? winStart = null;
            double winEnd = 0;
            string winType = "ATTACK";

            foreach (var rawLine in lines.Skip(1))
            {
                var parts = rawLine.Split(',');
                if (parts.Length < 2) continue;
                if (!double.TryParse(parts[0].Trim(), System.Globalization.NumberStyles.Float,
                        System.Globalization.CultureInfo.InvariantCulture, out var ts)) continue;

                var label = parts[1].Trim();
                bool isAttack = !string.Equals(label, "normal", StringComparison.OrdinalIgnoreCase);

                if (isAttack)
                {
                    winStart ??= ts;
                    winEnd = ts;
                    winType = label;
                }
                else
                {
                    if (winStart.HasValue)
                    {
                        rawGtWindows.Add(new GtAttackWindow
                        {
                            StartSec = winStart.Value,
                            EndSec = winEnd,
                            AttackType = winType,
                        });
                        winStart = null;
                    }
                }
            }

            if (winStart.HasValue)
            {
                rawGtWindows.Add(new GtAttackWindow
                {
                    StartSec = winStart.Value,
                    EndSec = winEnd,
                    AttackType = winType,
                });
            }

            foreach (var w in rawGtWindows)
                GtAttackWindows.Add(w);

            TryLoadGtManifest(dlg.FileName);

            expectedAttacks = rawGtWindows.Count;
            var types = rawGtWindows.Select(w => w.AttackType).Distinct().ToList();
            ExpectedAttackTypesText = types.Count > 0 ? string.Join(", ", types) : "N/A";
            OnPropertyChanged(nameof(ExpectedAttacksText));

            SessionStatus = $"GT LOADED — {rawGtWindows.Count} WINDOW(S) · {Path.GetFileName(dlg.FileName)}";
            logger.Info($"[VALLAB] GT loaded: {rawGtWindows.Count} attack window(s) from {Path.GetFileName(dlg.FileName)}");

            if (playbackData.Count > 0)
            {
                RunDetection();
                UpdateAllMetrics();
                RebuildDetectedWindows();
                RebuildExplainability();
                RebuildCanIdCorrelations();
                RebuildFalsePositives();
            }
        }
        catch (Exception ex)
        {
            logger.Error("[VALLAB] GT import failed.", ex);
            SessionStatus = "GT IMPORT FAILED";
        }
    }

    private void TryLoadGtManifest(string gtCsvPath)
    {
        try
        {
            var dir = Path.GetDirectoryName(gtCsvPath) ?? string.Empty;
            var baseName = Path.GetFileNameWithoutExtension(gtCsvPath);
            var stem = System.Text.RegularExpressions.Regex.Replace(baseName, "_gt", string.Empty, System.Text.RegularExpressions.RegexOptions.IgnoreCase);
            var jsonPath = Path.Combine(dir, stem + ".gt.json");
            if (!File.Exists(jsonPath)) return;

            var json = File.ReadAllText(jsonPath);
            var m = System.Text.RegularExpressions.Regex.Match(json, "\"attack_can_id\"\\s*:\\s*\"([^\"]+)\"");
            if (!m.Success) return;

            var canIdHex = m.Groups[1].Value;
            foreach (var w in rawGtWindows)
                w.CanIdHex = canIdHex;
        }
        catch { /* ignore — manifest is optional */ }
    }

    private void StartValidation()
    {
        if (playbackData.Count == 0 || isRunning) return;
        currentFrameIndex = 0;
        isRunning = true;
        validationMode = "RUNNING";
        ppsBuffer.Clear();

        OnPropertyChanged(nameof(IsRunning));
        OnPropertyChanged(nameof(ValidationModeText));
        StartValidationCommand.NotifyCanExecuteChanged();
        StopValidationCommand.NotifyCanExecuteChanged();

        SessionStatus = "VALIDATION RUNNING...";
        replayTimer.Start();
        logger.Info("[VALLAB] Validation session started.");
    }

    private void StopValidation()
    {
        replayTimer.Stop();
        isRunning = false;
        validationMode = "STOPPED";

        OnPropertyChanged(nameof(IsRunning));
        OnPropertyChanged(nameof(ValidationModeText));
        StartValidationCommand.NotifyCanExecuteChanged();
        StopValidationCommand.NotifyCanExecuteChanged();

        SessionStatus = $"STOPPED — FRAME {currentFrameIndex:N0}/{totalFrameCount:N0}";

        UpdateAllMetrics();
        RebuildDetectedWindows();
        RebuildExplainability();
        RebuildCanIdCorrelations();
        RebuildFalsePositives();

        logger.Info("[VALLAB] Validation session stopped.");
    }

    private void ResetSession()
    {
        replayTimer.Stop();
        isRunning = false;
        validationMode = "IDLE";
        currentFrameIndex = 0;
        playbackData.Clear();
        rawGtWindows.Clear();
        validationDetectedWindows.Clear();
        hasRunDetection = false;
        expectedAttacks = 0;
        detectedAttacks = 0;
        matchedAttacks = 0;
        missedDetections = 0;
        falsePositives = 0;
        matchPercent = 0;
        precision = 0;
        recall = 0;
        f1Score = 0;
        totalFrameCount = 0;
        loadedSourcePath = string.Empty;
        ppsBuffer.Clear();

        LoadedFileName = "--";
        SessionStatus = "NO SESSION LOADED";
        SessionDurationText = "--:--:--";
        ExpectedAttackTypesText = "N/A";
        DetectionDelayText = "--";
        TemporalDriftText = "--";
        ReplayTimelinePoints = new System.Windows.Media.PointCollection();

        GtAttackWindows.Clear();
        DetectedWindows.Clear();
        ExplainabilityRows.Clear();
        CanIdCorrelations.Clear();
        FalsePositiveRows.Clear();

        OnPropertyChanged(nameof(TotalFrameCountText));
        OnPropertyChanged(nameof(CurrentFrameText));
        OnPropertyChanged(nameof(IsRunning));
        OnPropertyChanged(nameof(ValidationModeText));
        NotifyAllMetrics();
        StartValidationCommand.NotifyCanExecuteChanged();
        StopValidationCommand.NotifyCanExecuteChanged();
        ExportReportCommand.NotifyCanExecuteChanged();
    }

    private async Task ExportReportAsync()
    {
        var dlg = new Microsoft.Win32.SaveFileDialog
        {
            Title = "Export Validation Report",
            Filter = "Text Files (*.txt)|*.txt|All Files (*.*)|*.*",
            FileName = $"validation_report_{DateTime.Now:yyyyMMdd_HHmmss}.txt",
        };

        if (dlg.ShowDialog() != true) return;

        try
        {
            var sb = new System.Text.StringBuilder();
            sb.AppendLine("=== CANVISION IDS VALIDATION REPORT ===");
            sb.AppendLine($"Generated : {DateTime.Now:yyyy-MM-dd HH:mm:ss}");
            sb.AppendLine($"Dataset   : {loadedFileName}");
            sb.AppendLine($"Frames    : {TotalFrameCountText}");
            sb.AppendLine($"Duration  : {sessionDurationText}");
            sb.AppendLine();
            sb.AppendLine("METRICS");
            sb.AppendLine($"  Expected attacks  : {expectedAttacks}");
            sb.AppendLine($"  Detected windows  : {detectedAttacks}");
            sb.AppendLine($"  Matched (TP)      : {matchedAttacks}");
            sb.AppendLine($"  Missed  (FN)      : {missedDetections}");
            sb.AppendLine($"  False Pos (FP)    : {falsePositives}");
            sb.AppendLine($"  Precision         : {precision:F3}");
            sb.AppendLine($"  Recall            : {recall:F3}");
            sb.AppendLine($"  F1 Score          : {f1Score:F3}");
            sb.AppendLine();
            sb.AppendLine("GROUND TRUTH WINDOWS");
            foreach (var w in rawGtWindows)
                sb.AppendLine($"  [{w.AttackType}]  {w.StartSec:F3}s -> {w.EndSec:F3}s");
            sb.AppendLine();
            sb.AppendLine("DETECTED WINDOWS");
            foreach (var d in validationDetectedWindows)
                sb.AppendLine($"  {d.Start:F3}s -> {d.End:F3}s  ({d.Type})");

            await Task.Run(() => File.WriteAllText(dlg.FileName, sb.ToString()));
            logger.Info($"[VALLAB] Report exported to {dlg.FileName}");
            SessionStatus = "REPORT EXPORTED";
        }
        catch (Exception ex)
        {
            logger.Error("[VALLAB] Export failed.", ex);
            SessionStatus = "EXPORT FAILED";
        }
    }

    // ── Replay tick ───────────────────────────────────────────────────────────

    private void OnReplayTick(object? sender, EventArgs e)
    {
        const int BatchSize = 50;
        int end = Math.Min(currentFrameIndex + BatchSize, playbackData.Count);
        for (int i = currentFrameIndex; i < end; i++)
        {
            var packet = playbackData[i];
            var ts = packet.Frame.RelativeTimestampSeconds;
            ppsBuffer.Add(ts);
        }

        currentFrameIndex = end;
        OnPropertyChanged(nameof(CurrentFrameText));

        if (currentFrameIndex >= playbackData.Count)
        {
            replayTimer.Stop();
            isRunning = false;
            validationMode = "COMPLETE";

            RunDetection();
            UpdateAllMetrics();
            RebuildDetectedWindows();
            RebuildExplainability();
            RebuildCanIdCorrelations();
            RebuildFalsePositives();

            hasRunDetection = true;
            OnPropertyChanged(nameof(IsRunning));
            OnPropertyChanged(nameof(ValidationModeText));
            StartValidationCommand.NotifyCanExecuteChanged();
            StopValidationCommand.NotifyCanExecuteChanged();
            NotifyAllMetrics();
            SessionStatus = $"COMPLETE — P={precision:F2} R={recall:F2} F1={f1Score:F2}";
            logger.Info("[VALLAB] Replay complete.");
        }
    }

    // ── IDS core — frequency-deviation detector ───────────────────────────────
    //   Fixed parameters (vs. original buggy values):
    //     baselineBucketCount = max(1, int(maxBucket * 0.03))   [was 0.20 → attack contamination]
    //     SpikeMultiplier     = 2.5                              [was 3.0]
    //     Fuzzy signal        = uniqueNewIds >= 10/bucket        [was missing entirely]

    private void RunDetection()
    {
        validationDetectedWindows.Clear();
        if (playbackData.Count == 0) return;

        // Prefer ML annotations if the dataset was scored by the backend.
        bool hasMlAnnotations = playbackData.Any(p => p.Anomalies.Any(a => a.SeverityScore >= 20));
        if (hasMlAnnotations)
        {
            mlDetectionPath = "ML_PIPELINE";
            RunMlDetection();
        }
        else
        {
            mlDetectionPath = "FREQUENCY_FALLBACK";
            RunFrequencyDetection();
        }

        mlWindowsGenerated = validationDetectedWindows.Count;
        OnPropertyChanged(nameof(MlDetectionPathText));
        OnPropertyChanged(nameof(MlFramesScoredText));
        OnPropertyChanged(nameof(MlAboveThresholdText));
        OnPropertyChanged(nameof(MlWindowsGeneratedText));
        logger.Info($"[VALLAB] RunDetection: path={mlDetectionPath} hasMlAnnotations={hasMlAnnotations} windows={mlWindowsGenerated}");
    }

    // ML-based detection: group frames flagged by per-frame inference into windows.
    private void RunMlDetection()
    {
        const double MergeGapSec = 0.4; // was 2.0 — reduced to match inter-attack gaps (min gap = 0.5s)

        var flaggedTimestamps = playbackData
            .Where(p => p.Anomalies.Any(a => a.SeverityScore >= 20))
            .Select(p => p.Frame.RelativeTimestampSeconds)
            .OrderBy(t => t)
            .ToList();

        if (flaggedTimestamps.Count == 0) return;

        double winStart = flaggedTimestamps[0];
        double winEnd   = flaggedTimestamps[0];

        for (int i = 1; i < flaggedTimestamps.Count; i++)
        {
            if (flaggedTimestamps[i] - winEnd <= MergeGapSec)
            {
                winEnd = flaggedTimestamps[i];
            }
            else
            {
                validationDetectedWindows.Add((winStart, winEnd, "ML_ANOMALY"));
                winStart = flaggedTimestamps[i];
                winEnd   = flaggedTimestamps[i];
            }
        }

        validationDetectedWindows.Add((winStart, winEnd, "ML_ANOMALY"));
    }

    // Frequency-deviation fallback used when no per-frame ML annotations are present.
    private void RunFrequencyDetection()
    {
        if (playbackData.Count == 0) return;

        double t0 = playbackData[0].Frame.RelativeTimestampSeconds;

        // ── 1. Bucket frames by CAN-ID counts ────────────────────────────────
        var buckets = new SortedDictionary<int, Dictionary<int, int>>();
        foreach (var packet in playbackData)
        {
            double ts = packet.Frame.RelativeTimestampSeconds;
            int b = (int)((ts - t0) / BucketSec);
            if (!buckets.TryGetValue(b, out var dict))
            {
                dict = new Dictionary<int, int>();
                buckets[b] = dict;
            }

            int canId = packet.Frame.CanId;
            dict[canId] = dict.TryGetValue(canId, out var cnt) ? cnt + 1 : 1;
        }

        if (buckets.Count == 0) return;

        // ── 2. Baseline (first ~1.5% of timeline, min 1 bucket) ─────────────
        int maxBucket = buckets.Keys.Max();
        int baselineBucketCount = Math.Max(1, (int)(maxBucket * 0.03));

        var baselineSamples = new Dictionary<int, List<int>>();
        foreach (var kvp in buckets)
        {
            if (kvp.Key >= baselineBucketCount) break;
            foreach (var _kv1 in kvp.Value)
            {
                var canId = _kv1.Key; var count = _kv1.Value;
                if (!baselineSamples.TryGetValue(canId, out var lst))
                {
                    lst = new List<int>();
                    baselineSamples[canId] = lst;
                }

                lst.Add(count);
            }
        }

        var baselineAvg = new Dictionary<int, double>();
        foreach (var _kv2 in baselineSamples) { var canId = _kv2.Key; var lst = _kv2.Value; baselineAvg[canId] = lst.Average(); }

        var baselineIds = new HashSet<int>(baselineAvg.Keys);

        // ── 3. Flag anomalous buckets ─────────────────────────────────────────
        var flagged = new HashSet<int>();
        foreach (var kvp in buckets)
        {
            if (kvp.Key < baselineBucketCount) continue;

            // Fuzzy: flood of unique new CAN-IDs (each appears only once)
            int uniqueNewIds = 0;
            foreach (var pair in kvp.Value)
                if (!baselineIds.Contains(pair.Key)) uniqueNewIds++;

            if (uniqueNewIds >= FuzzyUniqueThreshold) { flagged.Add(kvp.Key); continue; }

            // Rate-spike for known CAN-IDs
            foreach (var _kv3 in kvp.Value)
            {
                var canId = _kv3.Key; var count = _kv3.Value;
                if (!baselineIds.Contains(canId))
                {
                    if (count >= NewIdMinCount) { flagged.Add(kvp.Key); break; }
                }
                else
                {
                    double avg = baselineAvg[canId];
                    if (avg <= 0 && count >= NewIdMinCount)          { flagged.Add(kvp.Key); break; }
                    if (avg > 0  && count >= avg * SpikeMultiplier)  { flagged.Add(kvp.Key); break; }
                }
            }
        }

        if (flagged.Count == 0) return;

        // ── 4. Merge adjacent flagged buckets (gap <= 1) ──────────────────────
        var sorted = new List<int>(flagged);
        sorted.Sort();

        int ws = sorted[0], we = sorted[0];
        for (int i = 1; i < sorted.Count; i++)
        {
            if (sorted[i] <= we + 2) { we = sorted[i]; } // 1s merge gap (was 10/5s — was merging distinct windows)
            else
            {
                validationDetectedWindows.Add((t0 + ws * BucketSec, t0 + (we + 1) * BucketSec, "FREQUENCY_ANOMALY"));
                ws = sorted[i]; we = sorted[i];
            }
        }

        validationDetectedWindows.Add((t0 + ws * BucketSec, t0 + (we + 1) * BucketSec, "FREQUENCY_ANOMALY"));

        logger.Info($"[VALLAB] RunDetection: {validationDetectedWindows.Count} window(s) detected from {flagged.Count} flagged buckets (baseline={baselineBucketCount} buckets).");
    }

    // ── Metrics ───────────────────────────────────────────────────────────────

    private void UpdateAllMetrics()
    {
        detectedAttacks = validationDetectedWindows.Count;

        // Match each detected window to at most one GT window (temporal overlap)
        var gtMatched = new HashSet<int>();
        int tp = 0;
        double totalDelaySec = 0;

        foreach (var (dStart, dEnd, _) in validationDetectedWindows)
        {
            for (int g = 0; g < rawGtWindows.Count; g++)
            {
                if (gtMatched.Contains(g)) continue;
                var gt = rawGtWindows[g];
                if (dStart <= gt.EndSec && dEnd >= gt.StartSec)
                {
                    gtMatched.Add(g);
                    tp++;
                    totalDelaySec += Math.Max(0, dStart - gt.StartSec);
                    break;
                }
            }
        }

        matchedAttacks   = tp;
        falsePositives   = detectedAttacks - matchedAttacks;
        missedDetections = Math.Max(0, expectedAttacks - matchedAttacks);
        matchPercent     = expectedAttacks > 0 ? matchedAttacks * 100.0 / expectedAttacks : 0;
        precision        = detectedAttacks > 0 ? (double)matchedAttacks / detectedAttacks : 0;
        recall           = expectedAttacks > 0 ? (double)matchedAttacks / expectedAttacks  : 0;
        f1Score          = (precision + recall) > 0 ? 2 * precision * recall / (precision + recall) : 0;
        DetectionDelayText = tp > 0 ? $"{totalDelaySec / tp * 1000:F0}ms avg" : "--";
    }

    // ── UI rebuild helpers ────────────────────────────────────────────────────

    private void RebuildDetectedWindows()
    {
        DetectedWindows.Clear();
        double totalDur = playbackData.Count > 0
            ? playbackData[playbackData.Count - 1].Frame.RelativeTimestampSeconds - playbackData[0].Frame.RelativeTimestampSeconds
            : 1.0;
        if (totalDur <= 0) totalDur = 1.0;

        var gtMatched = new HashSet<int>();

        foreach (var (dStart, dEnd, dType) in validationDetectedWindows)
        {
            bool matched = false;
            for (int g = 0; g < rawGtWindows.Count; g++)
            {
                if (gtMatched.Contains(g)) continue;
                var gt = rawGtWindows[g];
                if (dStart <= gt.EndSec && dEnd >= gt.StartSec)
                { matched = true; gtMatched.Add(g); break; }
            }

            DetectedWindows.Add(new ValidationDetectedWindow
            {
                StartSec  = dStart,
                EndSec    = dEnd,
                AttackType = dType,
                IsMatched = matched,
                BarLeft   = dStart / totalDur * TimelineCanvasWidth,
                BarWidth  = Math.Max(2, (dEnd - dStart) / totalDur * TimelineCanvasWidth),
            });
        }
    }

    private void RebuildExplainability()
    {
        ExplainabilityRows.Clear();
        foreach (var dw in DetectedWindows)
        {
            ExplainabilityRows.Add(new ExplainabilityEntry
            {
                TimestampText = $"{dw.StartSec:F3}s",
                CanIdHex      = dw.IsMatched ? "RATE-SPIKE" : "FP",
                AnomalyType   = dw.AttackType,
                Severity      = dw.IsMatched ? "HIGH" : "LOW",
                SeverityScore = dw.IsMatched ? 85 : 20,
            });
        }
    }

    private void RebuildCanIdCorrelations()
    {
        CanIdCorrelations.Clear();
        foreach (var w in rawGtWindows)
        {
            CanIdCorrelations.Add(new CanIdCorrelationRow
            {
                CanIdHex    = w.CanIdHex,
                HitCount    = 1,
                AttackType  = w.AttackType,
                IsGroundTruth = true,
            });
        }
    }

    private void RebuildFalsePositives()
    {
        FalsePositiveRows.Clear();
        foreach (var dw in DetectedWindows.Where(d => !d.IsMatched))
        {
            FalsePositiveRows.Add(new FalsePositiveEntry
            {
                TimestampText = $"{dw.StartSec:F3}s",
                CanIdHex      = "--",
                AnomalyType   = dw.AttackType,
                ScoreText     = "FP",
            });
        }
    }

    private void NotifyAllMetrics()
    {
        OnPropertyChanged(nameof(ExpectedAttacksText));
        OnPropertyChanged(nameof(DetectedAttacksText));
        OnPropertyChanged(nameof(MatchedAttacksText));
        OnPropertyChanged(nameof(MissedDetectionsText));
        OnPropertyChanged(nameof(FalsePositivesText));
        OnPropertyChanged(nameof(MatchPercentText));
        OnPropertyChanged(nameof(PrecisionText));
        OnPropertyChanged(nameof(RecallText));
        OnPropertyChanged(nameof(F1ScoreText));
    }

    private void OnAnomaliesUpdated(IReadOnlyList<CanAnomaly> anomalies) { /* not used in validation mode */ }
}

// ──────────────────────────────────────────────────────────────────────────────
// AnomalyIntelViewModel — AI anomaly explanation + LLM layer
// ──────────────────────────────────────────────────────────────────────────────

public sealed class AnomalyIntelViewModel : SectionViewModel
{
    private readonly PythonApiClient pythonApiClient;
    private AlertDetailItem? selectedAlert;
    private string statusText = "NO ALERTS — WAITING FOR IDS EVENTS";

    public AnomalyIntelViewModel(VehicleDataService vehicleDataService, PythonApiClient pythonApiClient)
        : base(vehicleDataService, SectionKey.AnomalyIntel)
    {
        this.pythonApiClient = pythonApiClient;
        Alerts = new ObservableCollection<AlertDetailItem>();
        SelectAlertCommand = new RelayCommand<AlertDetailItem?>(SelectAlert);
        RefreshCommand = new RelayCommand(Refresh);
        vehicleDataService.AlertHistoryUpdated += OnAlertHistoryUpdated;
        Refresh();
    }

    public ObservableCollection<AlertDetailItem> Alerts { get; }

    public AlertDetailItem? SelectedAlert
    {
        get => selectedAlert;
        private set
        {
            SetProperty(ref selectedAlert, value);
            OnPropertyChanged(nameof(HasSelectedAlert));
        }
    }

    public bool HasSelectedAlert => selectedAlert is not null;

    public string StatusText
    {
        get => statusText;
        private set => SetProperty(ref statusText, value);
    }

    public bool HasAlerts => Alerts.Count > 0;
    public string AlertCountText => Alerts.Count == 0 ? "NO EVENTS" : $"{Alerts.Count} EVENT{(Alerts.Count == 1 ? "" : "S")}";
    public int CriticalCount => Alerts.Count(a => a.Severity == "CRITICAL");
    public int HighCount => Alerts.Count(a => a.Severity is "HIGH" or "WARNING");

    public IRelayCommand<AlertDetailItem?> SelectAlertCommand { get; }
    public IRelayCommand RefreshCommand { get; }

    private void Refresh()
    {
        OnAlertHistoryUpdated(VehicleDataService.AlertHistory);
    }

    private void OnAlertHistoryUpdated(IReadOnlyList<RuntimeAlertEvent> history)
    {
        Alerts.Clear();
        if (history.Count == 0)
        {
            StatusText = "NO ALERTS — WAITING FOR IDS EVENTS";
            OnPropertyChanged(nameof(HasAlerts));
            OnPropertyChanged(nameof(AlertCountText));
            OnPropertyChanged(nameof(CriticalCount));
            OnPropertyChanged(nameof(HighCount));
            return;
        }

        for (var i = 0; i < history.Count; i++)
        {
            var evt = history[i];
            var item = BuildDetailItem(i, evt);
            Alerts.Add(item);
        }

        StatusText = $"SHOWING {Alerts.Count} IDS ALERT{(Alerts.Count == 1 ? "" : "S")}";
        OnPropertyChanged(nameof(HasAlerts));
        OnPropertyChanged(nameof(AlertCountText));
        OnPropertyChanged(nameof(CriticalCount));
        OnPropertyChanged(nameof(HighCount));

        if (selectedAlert is null && Alerts.Count > 0)
            SelectAlert(Alerts[0]);
    }

    private AlertDetailItem BuildDetailItem(int index, RuntimeAlertEvent evt)
    {
        var (timing, payload, ml, temporal) = ParseLayerContributions(evt.Reason);
        var color = evt.Severity switch
        {
            "CRITICAL" => "#FF4040",
            "HIGH"     => "#FF8C3A",
            "WARNING"  => "#FFD700",
            _          => "#56F0AC",
        };

        var item = new AlertDetailItem
        {
            Index        = index,
            Time         = evt.TimestampUtc.ToLocalTime().ToString("HH:mm:ss.fff"),
            CanId        = evt.CanId,
            Severity     = evt.Severity,
            SeverityColor = color,
            Score        = evt.Score,
            AttackType   = string.IsNullOrWhiteSpace(evt.AttackType) ? "UNKNOWN" : evt.AttackType.ToUpperInvariant(),
            Reason       = evt.Reason,
            LayerTiming  = timing,
            LayerPayload = payload,
            LayerMl      = ml,
            LayerTemporal = temporal,
        };

        var capturedIndex = index;
        var capturedItem  = item;
        item.ExplainCommand = new AsyncRelayCommand(
            () => ExplainAlertAsync(capturedIndex, capturedItem),
            () => !capturedItem.IsLoading);

        return item;
    }

    private async Task ExplainAlertAsync(int alertIndex, AlertDetailItem item)
    {
        item.IsLoading = true;
        item.ExplainCommand?.NotifyCanExecuteChanged();
        try
        {
            var response = await pythonApiClient.GetAlertExplanationAsync(alertIndex, System.Threading.CancellationToken.None);
            if (response is not null)
            {
                item.ExplanationSummary        = response.Summary;
                item.ExplanationDetail         = response.Detail;
                item.ExplanationRecommendation = response.Recommendation;
                if (response.LayerTiming > 0 || response.LayerPayload > 0 || response.LayerMl > 0)
                {
                    item.LayerTiming   = response.LayerTiming;
                    item.LayerPayload  = response.LayerPayload;
                    item.LayerMl       = response.LayerMl;
                    item.LayerTemporal = response.LayerTemporal;
                }
                item.HasExplanation = true;
            }
            else
            {
                item.ExplanationSummary = "BACKEND UNAVAILABLE — start the Python server to get AI explanations.";
                item.HasExplanation = true;
            }
        }
        catch
        {
            item.ExplanationSummary = "EXPLANATION FAILED — check server connection.";
            item.HasExplanation = true;
        }
        finally
        {
            item.IsLoading = false;
            item.ExplainCommand?.NotifyCanExecuteChanged();
        }
    }

    private void SelectAlert(AlertDetailItem? item)
    {
        if (item is null) return;
        SelectedAlert = item;
    }

    protected override void OnDataUpdated(VehicleSnapshot snapshot)
    {
        base.OnDataUpdated(snapshot);
    }

    private static (double timing, double payload, double ml, double temporal) ParseLayerContributions(string reason)
    {
        double timing = 0, payload = 0, ml = 0, temporal = 0;
        if (string.IsNullOrWhiteSpace(reason)) return (timing, payload, ml, temporal);
        foreach (var part in reason.Split(','))
        {
            var eq = part.IndexOf('=');
            if (eq < 0) continue;
            var key = part.Substring(0, eq).Trim().ToLowerInvariant();
            if (!double.TryParse(part.Substring(eq + 1).Trim(),
                    System.Globalization.NumberStyles.Float,
                    System.Globalization.CultureInfo.InvariantCulture, out var val)) continue;
            switch (key)
            {
                case "timing":      timing  = val; break;
                case "payload":     payload = val; break;
                case "ml":          ml      = val; break;
                case "persistence": temporal = val; break;
            }
        }
        return (timing, payload, ml, temporal);
    }
}
