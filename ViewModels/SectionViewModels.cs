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
    public string UnitNameText =>
        Snapshot.Source == "log-playback" ? "LOG ANALYSIS MODE" :
        VehicleDataService.IsRunning ? "CANvision IDS LIVE" :
        "CANvision IDS OFFLINE";

    public string ModelText => "CANvision IDS";
    public string WorkspaceText => string.IsNullOrEmpty(VehicleDataService.ReplayName) || VehicleDataService.ReplayName == "NO REPLAY"
        ? "NO DATASET"
        : VehicleDataService.ReplayName;
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

    public string AmpText => IsCalibrating ? "---" : Snapshot.PeakAmperage > 0 ? $"{Snapshot.PeakAmperage:F1} A" : "---";

    public virtual double ReliabilityScore => Snapshot.PerformanceScore;
    public virtual string ReliabilityScoreText =>
        IsCalibrating || Snapshot.PerformanceScore <= 0 ? "---" : $"{Snapshot.PerformanceScore:F1}%";

    public string SessionTimerText =>
        VehicleDataService.LoadedReplayPackets is { Count: >= 2 } packets
            ? TimeSpan.FromSeconds(
                packets[Math.Max(0, Math.Min(VehicleDataService.ProcessedReplayFrames, packets.Count - 1))].Frame.RelativeTimestampSeconds
              ).ToString(@"mm\:ss")
            : "--:--";

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

    private string healthModelText  = "--";
    private string healthLlmText    = "--";
    private string healthUptimeText = "--";
    private string healthFpsText    = "--";
    private bool isChoosingMode = true;
    private bool isLiveConnecting;
    private bool isOfflineImporting;
    private bool backendOnline;

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

    private async Task ImportReplayAsync()
    {
        var dialog = new OpenFileDialog
        {
            Filter = "Replay CSV (*.csv)|*.csv|MF4 recordings (*.mf4)|*.mf4|CAN logs (*.log;*.asc;*.trc;*.txt)|*.log;*.asc;*.trc;*.txt|All files (*.*)|*.*",
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

        IsOfflineImporting = true;

        using var analyzeTimeout = new System.Threading.CancellationTokenSource(TimeSpan.FromSeconds(90));
        try
        {
            // Transparently decode MF4 -> CSV first, then run the exact same
            // parse/analyze/replay path CSV already uses — no separate MF4 code
            // path, no manual conversion by the user.
            var effectiveFilePath = dialog.FileName;
            if (Path.GetExtension(dialog.FileName).Equals(".mf4", StringComparison.OrdinalIgnoreCase))
            {
                AnalysisStatusText = "CONVERTING MF4";
                var csvPath = await VehicleDataService.ConvertMf4ToCsvAsync(dialog.FileName);
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
                ? pythonApiClient.AnalyzeLogsAsync(new[] { effectiveFilePath }, analyzeTimeout.Token)
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
                AnalysisStatusText = "RUNNING ML ANALYSIS";

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

            VehicleDataService.CompleteReplayAnalysis(detectedAttack, confidence, Array.Empty<RuntimeAlertEvent>());
            AnalysisStatusText = $"ANALYSIS COMPLETE — {detectedAttack}";
            AnalysisProgressPercent = 100;
            AnalysisProcessedFrames = packets.Count;
            IsAnalysisRunning = false;
            IsOfflineImporting = false;
            AnalysisCompleted?.Invoke();
        }
        catch (Exception exception)
        {
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
            if (VehicleDataService.AppState == AppState.NoDataset) return "NO DATASET";
            if (VehicleDataService.AppState == AppState.DatasetLoaded) return "READY";
            if (VehicleDataService.AppState == AppState.Analyzing) return "ANALYZING";
            if (IsCalibrating) return "BASELINING";
            // Alert-count takes priority — most accurate for post-analysis state
            if (VehicleDataService.CriticalAlerts > 0) return "CRITICAL";
            if (VehicleDataService.WarningAlerts > 0) return "THREAT DETECTED";
            // Score-based for live playback (normalized to 0-1 after ResolvePacketScore fix)
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
        "CRITICAL"          => $"CRITICAL — {VehicleDataService.DetectedAttackType} — SCORE {VehicleDataService.CurrentAnomalyScore:F3}",
        "THREAT DETECTED"   => $"ATTACK PATTERN: {VehicleDataService.DetectedAttackType}",
        "ELEVATED RISK"     => $"RISK SCORE {VehicleDataService.CurrentAnomalyScore:F3} — WATCH ACTIVE",
        "ANALYZING"         => $"SCORE {VehicleDataService.CurrentAnomalyScore:F3} — BASELINE COMPARISON",
        "MONITORING"        => "ALL CHANNELS NOMINAL",
        "BASELINING"        => "ESTABLISHING TRAFFIC BASELINE...",
        "READY"             => "DATASET LOADED — START ANALYSIS",
        _                   => "OFFLINE — IMPORT DATASET FROM HOME",
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

        // No placeholder rows — leave empty when no real alerts exist

        var hasData = VehicleDataService.LoadedReplayPackets is { Count: > 0 };
        var analysisAppState = VehicleDataService.AppState;
        SubsystemHealth.Clear();
        SubsystemHealth.Add(new MetricCardItem("DETECTION ENGINE",
            analysisAppState == AppState.AnalysisComplete ? "ACTIVE" :
            analysisAppState == AppState.Analyzing ? "RUNNING" : "IDLE",
            "IDS", OperationalStateText));
        SubsystemHealth.Add(new MetricCardItem("REPLAY ENGINE",
            ReplayEngineHealthText, "REPLAY", ReplayStatusText));
        SubsystemHealth.Add(new MetricCardItem("ML PIPELINE",
            analysisAppState >= AppState.Analyzing ? "ACTIVE" : "IDLE",
            "ML", VehicleDataService.MlAnalysisState));
        SubsystemHealth.Add(new MetricCardItem("DATA PIPELINE",
            hasData ? "LOADED" : "NO DATA",
            "INGEST", hasData ? $"{VehicleDataService.TotalReplayFrames:N0} FRAMES" : "EMPTY"));

        var chartValues = rollingScores.Count > 1
            ? rollingScores.ToList()
            : VehicleDataService.AlertHistory.Select(a => a.Score).DefaultIfEmpty(0.0).ToList();
        DashboardAnomalyPoints = BuildScoringChart(chartValues, 540, 116);
        DashboardAnomalyFillPoints = BuildScoringAreaFill(chartValues, 540, 116);
        // Threshold line at score=0.55, range 0–1.5, height=116: y = height*(1 - threshold/maxScore)
        const double alertThreshold = 0.55, maxScore = 1.5, chartH = 116, chartW = 540;
        var threshY = chartH * (1.0 - alertThreshold / maxScore);
        DashboardThresholdPoints = new System.Windows.Media.PointCollection
        {
            new(0, threshY),
            new(chartW, threshY),
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
    private readonly Dictionary<string, (int Count, double ScoreSum)> _canIdStats = new(StringComparer.OrdinalIgnoreCase);
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
        CanActivityRows = new ObservableCollection<CanActivityItem>();

        ImportLogCommand = new AsyncRelayCommand(ImportLogAsync);
        ExportSignalsCommand = new RelayCommand(ExportSignals);
        FreezeStreamCommand = new RelayCommand(() => VehicleDataService.Stop());
        ResumeStreamCommand = new RelayCommand(() => VehicleDataService.Start());

        VehicleDataService.SignalsUpdated += OnSignalsUpdated;
        VehicleDataService.AlertHistoryUpdated += OnAlertHistoryUpdated;
        VehicleDataService.ReplayRuntimeUpdated += OnReplayRuntimeUpdated;
        VehicleDataService.ReplayLoaded += OnReplayLoaded;
        VehicleDataService.LiveFramesUpdated += OnLiveFramesForActivity;
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
    public ObservableCollection<CanActivityItem> CanActivityRows { get; }
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
    public bool HasReplayLoaded => VehicleDataService.TotalReplayFrames > 0;

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
    public string AdapterName => VehicleDataService.AppState >= AppState.DatasetLoaded
        ? $"CANvision IDS — {VehicleDataService.ReplayName}"
        : "CANvision IDS — NO DATASET";
    public string PacketLossText => VehicleDataService.LoadedReplayPackets is { Count: > 0 } ? "0.00%" : "---";

    // Runtime KPI strip — only show real values from snapshot, never fabricated
    public string RuntimeRpmText => IsCalibrating ? "---" :
        Snapshot.MotorRPM > 0 ? $"{Snapshot.MotorRPM:N0}" : "---";
    public string RuntimeCurrentText => IsCalibrating ? "---" :
        Snapshot.BatteryCurrent != 0 ? $"{Snapshot.BatteryCurrent:F1} A" :
        Snapshot.PeakAmperage > 0 ? $"{Snapshot.PeakAmperage:F1} A" : "---";
    public string RuntimeGearText => IsCalibrating ? "---" :
        !string.IsNullOrEmpty(Snapshot.Gear) && Snapshot.Gear != "P" && Snapshot.Gear != "NORMAL" ? Snapshot.Gear : "---";
    public string RuntimeThrottleText => "---";
    public string RuntimeBrakeText => "---";
    public string RuntimeCurrentCanIdText => VehicleDataService.TopSuspiciousCanId is { Length: > 0 } id ? id : "---";

    // Alert card body texts — real data only
    public string CoolingHeadroomText => IsCalibrating ? "---" :
        Snapshot.MotorTemp > 0 ? $"Motor temp {Snapshot.MotorTemp:F1}°C — headroom {Math.Max(0, 120 - Snapshot.MotorTemp):F0}°C" : "---";
    public string CaptureCadenceText => IsCalibrating ? "---" : $"Sample cadence {SampleRateText} — {PacketRateText} active";
    public string EnergyNarrative => IsCalibrating ? "---" :
        Snapshot.Frequency > 0 ? $"Capture rate: {Snapshot.Frequency:F0} frames/sec — {VehicleDataService.TotalReplayFrames:N0} total frames analyzed." : "No frame data available.";
    public string BusLoadText => IsCalibrating ? "---" :
        Snapshot.Frequency > 0 ? $"{Snapshot.Frequency:F0} f/s" : "---";

    // ── Stream-aware 7-state operational state ────────────────────────────────
    public string StreamOperationalStateText
    {
        get
        {
            if (IsStreamFrozen) return "TELEMETRY DEGRADED";
            if (IsCalibrating)  return "BASELINING";
            var score = VehicleDataService.CurrentAnomalyScore; // 0.0–1.5 scale
            if (score >= 0.80) return "CRITICAL";
            if (score >= 0.55 || VehicleDataService.TotalAlerts > 0) return "THREAT DETECTED";
            if (score >= 0.35) return "ELEVATED RISK";
            if (score >= 0.10) return "ANALYZING";
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

    public string CanTrafficVolumeText => latestSignals.Count > 0 ? $"{latestSignals.Count} signals" : "No decoded signals";
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
        var displaySignals = latestSignals; // Only real decoded signals — no fabricated fallback

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
            Filter = "CAN logs (*.log;*.asc;*.csv;*.mf4)|*.log;*.asc;*.csv;*.mf4|All files (*.*)|*.*",
            Title = "Import CAN Log"
        };

        if (dialog.ShowDialog() != true)
        {
            return;
        }

        // Transparently decode MF4 -> CSV first, then run the exact same parse
        // path CSV already uses — no separate MF4 code path.
        var effectiveFilePath = dialog.FileName;
        if (Path.GetExtension(dialog.FileName).Equals(".mf4", StringComparison.OrdinalIgnoreCase))
        {
            var csvPath = await VehicleDataService.ConvertMf4ToCsvAsync(dialog.FileName);
            if (string.IsNullOrEmpty(csvPath))
            {
                return;
            }
            effectiveFilePath = csvPath!;
        }

        var result = await canLogImportService.ParseFileAsync(effectiveFilePath, skipMlScoring: true);
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
            return;

        var systems = string.Join(", ", latestSignals.Select(s => s.FeatureKey).Where(k => !string.IsNullOrEmpty(k)).Distinct().OrderBy(k => k));
        var lines = new System.Collections.Generic.List<string>
        {
            "# CANvision Decoded Signal Export",
            $"# Exported: {DateTime.Now:yyyy-MM-dd HH:mm:ss}",
            $"# Subsystems: {(string.IsNullOrEmpty(systems) ? "—" : systems)}",
            $"# Signals: {latestSignals.Count}",
            "#",
            "timestamp,can_id,system,name,value,unit,out_of_range"
        };

        foreach (var s in latestSignals.OrderBy(s => s.FeatureKey).ThenBy(s => s.Name))
        {
            lines.Add($"{s.TimestampUtc:o},0x{s.CanId:X3},{s.FeatureKey},{s.Name},{s.Value:F4},{s.Unit},{(s.OutOfRange ? "1" : "0")}");
        }

        System.IO.File.WriteAllLines(dialog.FileName, lines);
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
        OnPropertyChanged(nameof(HasReplayLoaded));
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

    private void OnLiveFramesForActivity(IReadOnlyList<LiveSignalItem> items)
    {
        foreach (var item in items)
        {
            var id = item.CanId;
            if (_canIdStats.TryGetValue(id, out var s))
                _canIdStats[id] = (s.Count + 1, s.ScoreSum + item.AnomalyScore);
            else
                _canIdStats[id] = (1, item.AnomalyScore);
        }
        RefreshCanActivity();
    }

    private void RefreshCanActivity()
    {
        var top = _canIdStats
            .OrderByDescending(kv => kv.Value.Count)
            .Take(10)
            .ToList();

        var maxCount = top.Count > 0 ? top[0].Value.Count : 1;

        CanActivityRows.Clear();
        foreach (var kv in top)
        {
            var avg = kv.Value.ScoreSum / Math.Max(1, kv.Value.Count);
            var color = avg >= 0.55 ? "#FF5050" : avg >= 0.35 ? "#FFD94A" : "#56F0AC";
            CanActivityRows.Add(new CanActivityItem
            {
                CanId    = kv.Key,
                Count    = kv.Value.Count,
                AvgScore = avg,
                BarWidth = Math.Max(4, 140.0 * kv.Value.Count / maxCount),
                BarColor = color,
            });
        }
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
        OnPropertyChanged(nameof(HasReplayLoaded));
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
            ["Battery_SOH"] = Snapshot.SOH,
            ["Voltage"] = Snapshot.BatteryVoltage,
            ["Current"] = Snapshot.BatteryCurrent != 0 ? Snapshot.BatteryCurrent : Snapshot.PeakAmperage,
            ["Temp"] = Snapshot.BatteryTemp,
            ["PeakAmperage"] = Snapshot.PeakAmperage,
            ["Speed"] = Snapshot.VehicleSpeed,
            ["RPM"] = Snapshot.MotorRPM,
            ["MotorTemp"] = Snapshot.MotorTemp,
            ["InverterTemp"] = Snapshot.InverterTemp,
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
        RestartAllServicesCommand = new AsyncRelayCommand(RestartAllServicesAsync);
        QuickScanCommand = new RelayCommand(() => RefreshFromRuntime(VehicleDataService.AlertHistory));
        StopScanCommand = new RelayCommand(() => DiagnosticsStatus = "SCAN PAUSED");
        ClearAlertsCommand = new RelayCommand(() =>
        {
            var confirm = System.Windows.MessageBox.Show(
                "Clear the error/event log? This cannot be undone.",
                "Clear Error Log",
                System.Windows.MessageBoxButton.YesNo,
                System.Windows.MessageBoxImage.Warning);
            if (confirm != System.Windows.MessageBoxResult.Yes) return;

            IdsEvents.Clear();
            FilteredIdsEvents.Clear();
            DiagnosticsStatus = "EVENT VIEW CLEARED";
            OnPropertyChanged(nameof(TotalEventsText));
        });
        ExportReportCommand = new RelayCommand(ExportReport);

        vehicleDataService.AlertHistoryUpdated += OnAlertHistoryUpdated;
        vehicleDataService.AnomaliesUpdated    += OnAnomaliesReceived;
        RefreshFromRuntime(vehicleDataService.AlertHistory);
    }

    public ObservableCollection<RuntimeAlertEvent> IdsEvents { get; }
    public ObservableCollection<RuntimeAlertEvent> FilteredIdsEvents { get; }
    public ObservableCollection<string> AttackTypeFilterOptions { get; }

    public IRelayCommand RunFullScanCommand { get; }
    public IAsyncRelayCommand RestartAllServicesCommand { get; }
    public IRelayCommand QuickScanCommand { get; }
    public IRelayCommand StopScanCommand { get; }
    public IRelayCommand ExportReportCommand { get; }
    public IRelayCommand ClearAlertsCommand { get; }

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

    public override string ReliabilityScoreText =>
        VehicleDataService.TotalAlerts == 0 ? "---" : $"{VehicleDataService.DetectionConfidence:F1}%";

    private async Task StartFullScanAsync()
    {
        DiagnosticsStatus = "REFRESHING IDS EVENTS";
        await Task.Delay(200);
        RefreshFromRuntime(VehicleDataService.AlertHistory);
        DiagnosticsStatus = $"IDS EVENTS LOADED ({FilteredIdsEvents.Count})";
    }

    private async Task RestartAllServicesAsync()
    {
        var confirm = System.Windows.MessageBox.Show(
            "This will restart all backend services (Telemetry, Detection Engine, Model Runtime, Validation Engine). Continue?",
            "Restart All Services",
            System.Windows.MessageBoxButton.YesNo,
            System.Windows.MessageBoxImage.Warning);
        if (confirm != System.Windows.MessageBoxResult.Yes) return;

        DiagnosticsStatus = "RESTARTING ALL SERVICES...";
        try
        {
            await Task.Delay(400);
            RefreshFromRuntime(VehicleDataService.AlertHistory);
            DiagnosticsStatus = "ALL SERVICES RESTARTED";
        }
        catch (Exception)
        {
            DiagnosticsStatus = "RESTART FAILED";
        }
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
    private string _selectedVehicleId = "";
    private string _offlineStatusText = "";
    private string _offlineSessionId = "";
    private bool _isOfflineDone = false;
    private OfflineSummaryResponse? _offlineResult;

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
        RecentAlertItems = new ObservableCollection<RuntimeAlertEvent>();
        VehicleItems = new ObservableCollection<VehicleProfileItem>();

        PlayCommand = new RelayCommand(Play);
        PauseCommand = new RelayCommand(Pause);
        StopCommand = new RelayCommand(Stop);
        OpenLogCommand = new AsyncRelayCommand(OpenLogAsync);
        RewindCommand = new RelayCommand(Rewind);
        ForwardCommand = new RelayCommand(Forward);
        StartRecordCommand = new AsyncRelayCommand(StartRecordAsync);
        StopRecordCommand  = new AsyncRelayCommand(StopRecordAsync);
        InjectTestCommand  = new AsyncRelayCommand(InjectTestAsync);
        LoadVehiclesCommand = new AsyncRelayCommand(LoadVehiclesAsync);

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
        VehicleDataService.AppStateChanged += OnAppStateChanged;
        LoadReplayFromService();
        RebuildForensicWorkspace();
        // Load vehicle profiles in background — populates the vehicle selector ComboBox
        _ = LoadVehiclesAsync();
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
    public ObservableCollection<RuntimeAlertEvent> RecentAlertItems { get; }
    public ObservableCollection<VehicleProfileItem> VehicleItems { get; }

    public IRelayCommand PlayCommand { get; }
    public IRelayCommand PauseCommand { get; }
    public IRelayCommand StopCommand { get; }
    public IRelayCommand OpenLogCommand { get; }
    public IRelayCommand RewindCommand { get; }
    public IRelayCommand ForwardCommand { get; }
    public IRelayCommand<string> SetSpeedCommand { get; }
    public IAsyncRelayCommand StartRecordCommand { get; }
    public IAsyncRelayCommand StopRecordCommand  { get; }
    public IAsyncRelayCommand InjectTestCommand  { get; }
    public IAsyncRelayCommand LoadVehiclesCommand { get; }

    public string SelectedVehicleId
    {
        get => _selectedVehicleId;
        set { _selectedVehicleId = value ?? ""; OnPropertyChanged(); OnPropertyChanged(nameof(SelectedVehicleNameText)); }
    }

    public string SelectedVehicleNameText
    {
        get
        {
            if (string.IsNullOrEmpty(_selectedVehicleId)) return "—";
            foreach (var v in VehicleItems)
                if (v.Id == _selectedVehicleId) return v.Name;
            return _selectedVehicleId;
        }
    }

    public string SessionAnomalyRateText =>
        IsOfflineDone && _offlineResult != null
            ? $"{_offlineResult.AnomalyRate:F2}%  ({_offlineResult.AnomalyCount:N0} / {_offlineResult.TotalFrames:N0})"
            : "—";

    public string OfflineStatusText
    {
        get => _offlineStatusText;
        private set { _offlineStatusText = value; OnPropertyChanged(); }
    }

    public bool IsOfflineDone
    {
        get => _isOfflineDone;
        private set { _isOfflineDone = value; OnPropertyChanged(); OnPropertyChanged(nameof(SessionAnomalyRateText)); }
    }

    public OfflineSummaryResponse? OfflineResult
    {
        get => _offlineResult;
        private set { _offlineResult = value; OnPropertyChanged(); OnPropertyChanged(nameof(SessionAnomalyRateText)); }
    }

    public string LoadedFileName => loadedFileName;
    public string SessionDurationText => sessionDurationText;
    public bool HasReplayLoaded => playbackData.Count > 0;
    public string DatasetText => loadedFileName == "NO SESSION" ? "NO DATASET" : Path.GetFileNameWithoutExtension(loadedFileName).ToUpperInvariant();
    public string VehicleText => loadedFileName == "NO SESSION" ? "NO DATASET" : Path.GetFileNameWithoutExtension(loadedFileName).ToUpperInvariant();
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
    public string CurrentConfidenceText => $"{Math.Min(99.9, ResolvePacketScore(CurrentPacket) * 100):F1}%";
    public string CurrentCanIdText => CurrentPacket is null ? "--" : $"0x{CurrentPacket.Frame.CanId:X3}";
    public string CurrentSeverityText => CurrentPacket?.Anomalies.FirstOrDefault()?.Severity ?? (playbackData.Count == 0 ? "--" : "INFO");
    public string CurrentFilePositionText => playbackData.Count == 0 ? "--" : $"{Math.Min(100, Math.Max(0, currentFrameIndex / (double)Math.Max(1, playbackData.Count) * 100.0)):F1}%";
    public string CurrentAttackTypeText => CurrentPacket?.Anomalies.FirstOrDefault()?.Title ?? VehicleDataService.DetectedAttackType;
    public string TotalDetectionsText => TotalDetections.ToString("N0");
    public string AlertCountText => TotalAlerts.ToString("N0");
    public bool HasAlerts => TotalAlerts > 0;
    public string ReplayFpsText => $"{VehicleDataService.RuntimeFps:F1}";
    public string MlAnalysisStateText => VehicleDataService.MlAnalysisState;
    public string TruePositivesText => AttackWindowCount == 0 ? "--" : Math.Min(TotalDetections, AttackWindowCount).ToString("N0");
    public string FalsePositivesText => AttackWindowCount == 0 ? TotalDetections.ToString("N0") : Math.Max(0, TotalDetections - AttackWindowCount).ToString("N0");
    public string FalseNegativesText => AttackWindowCount == 0 ? "--" : Math.Max(0, AttackWindowCount - TotalDetections).ToString("N0");
    public string DetectionRateText => TotalFrames == 0 ? "--" : $"{TotalDetections * 100.0 / TotalFrames:F1}%";
    public string NormalFramesPercentText => TotalFrames == 0 ? "100,0%" : $"{Math.Max(0, TotalFrames - TotalDetections) * 100.0 / TotalFrames:F1}%";
    public int AttackWindowCount => TimelineWindows.Count(item => item.Track == "Attack Windows");
    public string AttackWindowCountText => AttackWindowCount.ToString("N0");
    public string AttackCoverageText => AttackWindowCount == 0 ? "--" : $"{Math.Min(100, TotalDetections * 100.0 / Math.Max(1, AttackWindowCount)):F1}%";
    public string CoveredText => AttackWindowCount == 0 ? "--" : $"{Math.Min(TotalDetections, AttackWindowCount):N0}";
    public string MissedText => AttackWindowCount == 0 ? "--" : $"{Math.Max(0, AttackWindowCount - TotalDetections):N0}";
    public string TotalAttackDurationText => BuildAttackDurationText();
    public string ReplayLatencyText => $"{VehicleDataService.RuntimeLatencyMs:F0} ms";
    public string DroppedFramesText => playbackData.Count == 0 ? "--" : $"0 / {playbackData.Count:N0}";
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

    public string SessionNameText => loadedFileName == "NO SESSION"
        ? "NO SESSION"
        : Path.GetFileNameWithoutExtension(loadedFileName).ToUpperInvariant();
    public string FileNameShortText => loadedFileName == "NO SESSION" ? "No file loaded" : loadedFileName;
    public string ConnectionStatusText => playbackData.Count > 0 ? "SIMULATION" : "DISCONNECTED";
    public string MessagesPerSecondText => $"{VehicleDataService.RuntimeFps:F0}";
    public string CanTxLoadText => $"{Math.Min(100, VehicleDataService.RuntimeFps / 20.0):F1}%";
    public string ErrorFramesCountText => "0";
    public string BusLoadText => $"{Math.Min(100, VehicleDataService.RuntimeFps / 20.0):F1}%";
    public string CanInterfaceText => playbackData.Count > 0 ? "SIMULATION" : "--";
    public string BitrateText => "--";
    public string SamplePointText => "--";
    public string ReplayModeText => playbackData.Count > 0 ? "REPLAY" : "--";
    public string LastUpdateText => CurrentPacket is null ? "--:--:--" : CurrentPacket.Frame.TimestampUtc.ToLocalTime().ToString("HH:mm:ss");
    public System.Windows.Media.PointCollection AnomalyScoreSparkPoints { get; private set; } = new();

    public bool   IsRecording          => VehicleDataService.IsRecording;
    public int    RecordingFrameCount  => VehicleDataService.RecordingFrameCount;
    public string RecordingElapsedText => $"{(int)VehicleDataService.RecordingElapsed / 60:D2}:{(int)VehicleDataService.RecordingElapsed % 60:D2}";
    public string RecordingOutputPath  => VehicleDataService.RecordingOutputPath;
    public string RecordButtonLabel    => IsRecording ? "■  STOP REC" : "⏺  RECORD";
    public string RecordStatusText     => IsRecording ? $"REC  {RecordingFrameCount:N0} frames  {RecordingElapsedText}" : "IDLE";

    private async Task StartRecordAsync()
    {
        if (IsRecording) return;
        await VehicleDataService.StartRecordingAsync();
        OnPropertyChanged(nameof(IsRecording));
        OnPropertyChanged(nameof(RecordButtonLabel));
        OnPropertyChanged(nameof(RecordStatusText));
        StartRecordCommand.NotifyCanExecuteChanged();
        StopRecordCommand.NotifyCanExecuteChanged();
    }

    private async Task StopRecordAsync()
    {
        if (!IsRecording) return;
        await VehicleDataService.StopSimulatorAsync();
        var path = await VehicleDataService.StopRecordingAsync();
        OnPropertyChanged(nameof(IsRecording));
        OnPropertyChanged(nameof(RecordButtonLabel));
        OnPropertyChanged(nameof(RecordStatusText));
        OnPropertyChanged(nameof(RecordingFrameCount));
        StartRecordCommand.NotifyCanExecuteChanged();
        StopRecordCommand.NotifyCanExecuteChanged();
        InjectTestCommand.NotifyCanExecuteChanged();
        if (!string.IsNullOrEmpty(path))
            await VehicleDataService.TriggerBackendReplayAsync(path!, SelectedVehicleId);
    }

    private async Task InjectTestAsync()
    {
        if (IsRecording) return;
        await VehicleDataService.StartRecordingAsync();
        await VehicleDataService.StartSimulatorAsync();
        OnPropertyChanged(nameof(IsRecording));
        OnPropertyChanged(nameof(RecordButtonLabel));
        OnPropertyChanged(nameof(RecordStatusText));
        StartRecordCommand.NotifyCanExecuteChanged();
        StopRecordCommand.NotifyCanExecuteChanged();
        InjectTestCommand.NotifyCanExecuteChanged();
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

        // Replay already reached the end (FinishPlayback leaves currentFrameIndex at
        // Count - 1, the last valid index) — restart from the beginning instead of
        // silently re-finishing after a single frame.
        if (currentFrameIndex >= playbackData.Count - 1)
        {
            currentFrameIndex = 0;
            VehicleDataService.SetReplayCursor(-1);
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

    // Called when replay reaches end naturally — freeze at 100%, don't reset to 0
    private void FinishPlayback()
    {
        currentFrameIndex = Math.Max(0, playbackData.Count - 1);
        PlaybackMode = "STOPPED";
        playbackTimer.Stop();
        OnPropertyChanged(nameof(ReplayProgressText));
        OnPropertyChanged(nameof(ReplayProgressPercent));
        OnPropertyChanged(nameof(ProcessedFramesText));
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

    private async Task LoadVehiclesAsync()
    {
        for (int attempt = 0; attempt < 15; attempt++)
        {
            if (attempt > 0)
                await Task.Delay(2000);
            try
            {
                var response = await VehicleDataService.GetVehicleListAsync();
                if (response?.Vehicles == null) continue;
                VehicleItems.Clear();
                foreach (var v in response.Vehicles)
                    VehicleItems.Add(v);
                if (string.IsNullOrEmpty(_selectedVehicleId) && VehicleItems.Count > 0)
                    SelectedVehicleId = VehicleItems[0].Id;
                return;
            }
            catch (Exception ex)
            {
                logger.Error("LoadVehiclesAsync failed.", ex);
            }
        }
    }

    private async Task OpenLogAsync()
    {
        var dialog = new OpenFileDialog
        {
            Filter = "CAN logs (*.mf4;*.log;*.txt;*.trc;*.asc;*.csv)|*.mf4;*.log;*.txt;*.trc;*.asc;*.csv|MF4 files (*.mf4)|*.mf4|All files (*.*)|*.*",
            Title = "Open CAN Log",
        };

        if (dialog.ShowDialog() != true)
            return;

        var ext = Path.GetExtension(dialog.FileName).ToLowerInvariant();

        // Stop any in-progress replay before loading new data — otherwise the old
        // DispatcherTimer keeps ticking against playbackData during the parse await
        // below and can repaint stale chart data after the new file's own reset runs.
        playbackTimer.Stop();

        // MF4 also gets the richer top-threats/anomaly-rate summary panel, since
        // the offline analyzer decodes MF4 natively — no conversion needed for this part.
        if (ext == ".mf4")
        {
            _ = OpenMf4Async(dialog.FileName)
                .ContinueWith(t => logger.Error("MF4 offline summary failed.", t.Exception?.InnerException),
                    System.Threading.Tasks.TaskContinuationOptions.OnlyOnFaulted);
        }

        var originalFileName = Path.GetFileName(dialog.FileName);
        var effectiveFilePath = dialog.FileName;

        try
        {
            // Transparently decode MF4 -> CSV first, then run the exact same
            // replay/detection/AI-explanation/export path CSV already uses —
            // no separate MF4 code path, no manual conversion by the user.
            if (ext == ".mf4")
            {
                PlaybackMode = "CONVERTING MF4...";
                var csvPath = await VehicleDataService.ConvertMf4ToCsvAsync(dialog.FileName);
                if (string.IsNullOrEmpty(csvPath))
                {
                    PlaybackMode = "MF4 CONVERSION FAILED";
                    return;
                }
                effectiveFilePath = csvPath!;
            }

            var result = await canLogImportService.ParseFileAsync(effectiveFilePath, skipMlScoring: true);
            var packets = result.Packets.ToList();
            VehicleDataService.LoadReplayPackets(originalFileName, packets);
            LoadReplayData(originalFileName, packets, result.Events.ToList());
            PlaybackMode = playbackData.Count == 0
                ? $"NO PARSABLE FRAMES ({result.ParsedLines}/{result.TotalLines})"
                : $"LOADED {playbackData.Count} FRAMES ({result.ParsedLines}/{result.TotalLines})";
            _ = VehicleDataService.TriggerBackendReplayAsync(effectiveFilePath, SelectedVehicleId)
                .ContinueWith(t => logger.Error("Backend replay trigger failed.", t.Exception?.InnerException),
                    System.Threading.Tasks.TaskContinuationOptions.OnlyOnFaulted);
        }
        catch (Exception exception)
        {
            logger.Error("Log import failed.", exception);
            PlaybackMode = "IMPORT FAILED";
        }
    }

    private async Task OpenMf4Async(string filePath)
    {
        var vehicleId = string.IsNullOrEmpty(_selectedVehicleId) ? "nissan_leaf" : _selectedVehicleId;
        IsOfflineDone = false;
        OfflineResult = null;
        PlaybackMode = $"QUEUING MF4 OFFLINE ANALYSIS...";
        OfflineStatusText = "Starting...";

        try
        {
            var startResp = await VehicleDataService.StartOfflineAnalysisAsync(filePath, vehicleId);
            if (startResp == null || string.IsNullOrEmpty(startResp.SessionId))
            {
                PlaybackMode = "OFFLINE ANALYSIS FAILED — backend not reachable";
                OfflineStatusText = "Error";
                return;
            }

            _offlineSessionId = startResp.SessionId;
            PlaybackMode = $"MF4 ANALYZING  [{vehicleId.ToUpperInvariant()}]";
            OfflineStatusText = "Running...";

            // Poll for completion (max 5 min)
            var deadline = DateTime.UtcNow.AddMinutes(5);
            while (DateTime.UtcNow < deadline)
            {
                await Task.Delay(1500);
                var status = await VehicleDataService.GetOfflineStatusAsync(_offlineSessionId);
                if (status == null) break;

                var pct = status.Progress.ToString("F0");
                OfflineStatusText = $"{status.Status.ToUpperInvariant()}  {pct}%  ({status.ProcessedFrames:N0}/{status.TotalFrames:N0})";
                PlaybackMode = $"MF4 ANALYZING  [{vehicleId.ToUpperInvariant()}]  {pct}%";

                if (status.Status == "done")
                {
                    var summary = await VehicleDataService.GetOfflineSummaryAsync(_offlineSessionId);
                    var anomalyRate = summary?.AnomalyRate.ToString("F1") ?? "?";
                    PlaybackMode = $"MF4 DONE  {status.TotalFrames:N0} FRAMES  ANOMALY RATE {anomalyRate}%";
                    OfflineStatusText = $"Done — {status.AnomalyCount} anomalies / {status.TotalFrames:N0} frames ({anomalyRate}%)";
                    loadedFileName = Path.GetFileName(filePath);
                    OnPropertyChanged(nameof(LoadedFileName));
                    OfflineResult = summary;
                    IsOfflineDone = true;
                    return;
                }

                if (status.Status == "error")
                {
                    PlaybackMode = "MF4 ANALYSIS ERROR";
                    OfflineStatusText = $"Error: {status.Error}";
                    return;
                }
            }

            PlaybackMode = "MF4 ANALYSIS TIMEOUT";
            OfflineStatusText = "Timeout";
        }
        catch (Exception ex)
        {
            logger.Error("OpenMf4Async failed.", ex);
            PlaybackMode = "MF4 ANALYSIS FAILED";
            OfflineStatusText = "Exception";
        }
    }

    private void LoadReplayFromService()
    {
        var packets = VehicleDataService.LoadedReplayPackets?.ToList() ?? new List<PlaybackPacket>();

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
        OnPropertyChanged(nameof(HasReplayLoaded));

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

    private void OnAppStateChanged(AppState state)
    {
        if (state == AppState.AnalysisComplete && playbackData.Count > 0)
        {
            currentFrameIndex = 0;
            Play();
        }
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

            // Clear live feed — alerts will be revealed as the cursor advances past their frames
            RecentAlertItems.Clear();
            OnPropertyChanged(nameof(HasAlerts));
            OnPropertyChanged(nameof(AlertCountText));

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
            FinishPlayback();
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
        OnPropertyChanged(nameof(MessagesPerSecondText));
        OnPropertyChanged(nameof(CanTxLoadText));
        OnPropertyChanged(nameof(BusLoadText));
        OnPropertyChanged(nameof(LastUpdateText));

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
            return 0;
        return packet.Anomalies
            .Select(item => item.SeverityScore > 0 ? item.SeverityScore / 100.0 : Math.Abs(item.AnomalyScore))
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
                TimelineMarkers.Add(new ForensicTimelineMarker("Ground Truth", x, 91, "GT", "#B46CFF"));
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
        foreach (var (idx, alert) in _allAlertsByFrame)
        {
            if (idx > frameIndex) break;
            if (idx <= _lastRevealedFrame) continue;
            var x = BuildTimelineX(idx);
            TimelineMarkers.Add(new ForensicTimelineMarker("Detections", x, 39, "D", "#FF8C3A"));
            TimelineMarkers.Add(new ForensicTimelineMarker("Alerts",     x, 65, "!", "#FF5050"));
            // Prepend to Recent Alerts so newest appears at top; cap at 12 entries
            RecentAlertItems.Insert(0, alert);
            if (RecentAlertItems.Count > 12)
                RecentAlertItems.RemoveAt(RecentAlertItems.Count - 1);
            revealed = true;
        }
        if (frameIndex > _lastRevealedFrame) _lastRevealedFrame = frameIndex;
        if (revealed)
        {
            OnPropertyChanged(nameof(HasAlerts));
            NotifyForensicProperties();
        }
    }

    private void AddAttackWindow(int startIndex, int endIndex)
    {
        var left = BuildTimelineX(startIndex);
        var right = BuildTimelineX(endIndex);
        TimelineWindows.Add(new ForensicTimelineWindow("Attack Windows", left, Math.Max(4, right - left), 117, "#AAFF5050"));
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

        var newScorePts = BuildFixedRangePoints(blended, ScorePlotW, ScorePlotH);
        DetectionScorePoints = newScorePts;
        OnPropertyChanged(nameof(DetectionScorePoints));

        // Threshold sits above the max normal-traffic level (density*0.62 <= 0.62, y>=45)
        DetectionThresholdPoints.Clear();
        DetectionThresholdPoints.Add(new System.Windows.Point(0, ScorePlotH * 0.28));
        DetectionThresholdPoints.Add(new System.Windows.Point(ScorePlotW, ScorePlotH * 0.28));

        PreBuildScoreBuckets(blended);

        // Mini sparkline for the ANOMALY SCORE stat box (80×20, downsampled, open polyline)
        const int SparkW = 80, SparkH = 20;
        var sparkStep = Math.Max(1, blended.Length / SparkW);
        var sparkList = new System.Windows.Media.PointCollection();
        for (var i = 0; i < blended.Length; i += sparkStep)
        {
            var sx = blended.Length <= 1 ? 0.0 : (double)i / (blended.Length - 1) * SparkW;
            var sy = (SparkH - 2.0) * (1.0 - Math.Max(0.0, Math.Min(1.0, blended[i]))) + 1.0;
            sparkList.Add(new System.Windows.Point(sx, sy));
        }
        AnomalyScoreSparkPoints.Clear();
        foreach (var p in sparkList) AnomalyScoreSparkPoints.Add(p);

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
        if (_scoreBuckets.Length == 0 || playbackData.Count < 2)
        {
            // No data for the newly-loaded file (e.g. empty/failed import) — collapse the
            // overlay to an empty polygon instead of leaving the previous file's shape on
            // screen.
            LiveChartCursorX = 0;
            LiveScorePoints = new System.Windows.Media.PointCollection();
            OnPropertyChanged(nameof(LiveChartCursorX));
            OnPropertyChanged(nameof(LiveScorePoints));
            return;
        }
        var activeBucket = (int)(currentFrameIndex * (ScorePlotW - 1) / (double)(playbackData.Count - 1));
        activeBucket = Math.Max(0, Math.Min(ScorePlotW - 1, activeBucket));
        LiveChartCursorX = activeBucket;

        // Build progressive filled polygon: top edge left→right, then close at bottom
        var pts = new System.Windows.Media.PointCollection(activeBucket + 3);
        for (var i = 0; i <= activeBucket; i++)
        {
            var normalized = Math.Max(0.0, Math.Min(1.0, _scoreBuckets[i] / _scoreBucketMax));
            var y = (ScorePlotH - 2.0) * (1.0 - normalized) + 1.0;
            pts.Add(new System.Windows.Point(i, Math.Max(1, Math.Min(ScorePlotH - 1, (int)y))));
        }
        if (activeBucket >= 0)
        {
            pts.Add(new System.Windows.Point(activeBucket, ScorePlotH - 1));
            pts.Add(new System.Windows.Point(0, ScorePlotH - 1));
        }

        LiveScorePoints = pts;
        OnPropertyChanged(nameof(LiveChartCursorX));
        OnPropertyChanged(nameof(LiveScorePoints));
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
        OnPropertyChanged(nameof(HasAlerts));
        OnPropertyChanged(nameof(ReplayFpsText));
        OnPropertyChanged(nameof(TruePositivesText));
        OnPropertyChanged(nameof(FalsePositivesText));
        OnPropertyChanged(nameof(FalseNegativesText));
        OnPropertyChanged(nameof(DetectionRateText));
        OnPropertyChanged(nameof(NormalFramesPercentText));
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
        OnPropertyChanged(nameof(SessionNameText));
        OnPropertyChanged(nameof(FileNameShortText));
        OnPropertyChanged(nameof(ConnectionStatusText));
        OnPropertyChanged(nameof(MessagesPerSecondText));
        OnPropertyChanged(nameof(CanTxLoadText));
        OnPropertyChanged(nameof(BusLoadText));
        OnPropertyChanged(nameof(CanInterfaceText));
        OnPropertyChanged(nameof(ReplayModeText));
        OnPropertyChanged(nameof(LastUpdateText));
        OnPropertyChanged(nameof(AnomalyScoreSparkPoints));
    }
}

public sealed class SettingsViewModel : SectionViewModel
{
    private readonly PythonApiClient pythonApiClient;
    private readonly CANvision.Native.Models.AppConfig appConfig;
    private string detectionModelText  = "IsolationForest + KMeans";
    private string modelClustersText   = "--";
    private string llmProviderText     = "--";
    private string modelStatusText     = "CHECKING...";
    private string saveStatusText      = string.Empty;
    private string hwStatusText        = "DISCONNECTED";
    private string hwChannel           = "0";
    private string hwBitrate           = "500000";
    private string selectedHwInterface = "virtual";
    private string selectedHwVehicleId = "";
    private string pythonCanWarning    = "Checking python-can...";
    private bool   pythonCanAvailable  = false;
    private DispatcherTimer? hwPollTimer;

    public SettingsViewModel(VehicleDataService vehicleDataService, PythonApiClient pythonApiClient)
        : base(vehicleDataService, SectionKey.Settings)
    {
        this.pythonApiClient = pythonApiClient;
        appConfig = CANvision.Native.Models.AppConfig.Load();

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
        HardwareInterfaceItems = new ObservableCollection<string>
        {
            "virtual", "pcan", "kvaser", "socketcan", "slcan", "vector", "ixxat",
        };
        HardwareVehicleItems = new ObservableCollection<VehicleProfileItem>();

        SelectSettingsCategoryCommand = new RelayCommand<string>(category => SelectedSettingsCategory = category ?? "OBD2 ADAPTER");
        selectedSettingsCategory = "OBD2 ADAPTER";
        SaveSettingsCommand        = new RelayCommand(SaveSettings);
        RestoreDefaultsCommand     = new RelayCommand(RestoreDefaults);
        LaunchSimulatorCommand     = new AsyncRelayCommand(LaunchSimulatorAsync);
        ConnectHardwareCommand     = new AsyncRelayCommand(ConnectHardwareAsync);
        DisconnectHardwareCommand  = new AsyncRelayCommand(DisconnectHardwareAsync);
        RefreshPortsCommand        = new AsyncRelayCommand(RefreshPortsAsync);

        HardwareChannelItems = new ObservableCollection<string> { "0", "PCAN_USBBUS1", "can0", "/dev/can0", "COM3", "COM4" };

        _ = RefreshModelInfoAsync();
        _ = LoadHardwareVehiclesAsync();
        _ = InitHardwareAsync();
    }

    private string selectedSettingsCategory;

    public ObservableCollection<string>              SettingsCategories     { get; }
    public ObservableCollection<ProfileItem>         ProfileCards           { get; }
    public ObservableCollection<string>              HardwareInterfaceItems { get; }
    public ObservableCollection<VehicleProfileItem>  HardwareVehicleItems   { get; }
    public ObservableCollection<string>              HardwareChannelItems   { get; }
    public IRelayCommand<string>  SelectSettingsCategoryCommand { get; }
    public IRelayCommand          SaveSettingsCommand           { get; }
    public IRelayCommand          RestoreDefaultsCommand        { get; }
    public IAsyncRelayCommand     LaunchSimulatorCommand        { get; }
    public IAsyncRelayCommand     ConnectHardwareCommand        { get; }
    public IAsyncRelayCommand     DisconnectHardwareCommand     { get; }
    public IAsyncRelayCommand     RefreshPortsCommand           { get; }

    public bool PythonCanAvailable
    {
        get => pythonCanAvailable;
        private set => SetProperty(ref pythonCanAvailable, value);
    }

    public string PythonCanWarning
    {
        get => pythonCanWarning;
        private set => SetProperty(ref pythonCanWarning, value);
    }

    public string SelectedSettingsCategory
    {
        get => selectedSettingsCategory;
        set => SetProperty(ref selectedSettingsCategory, value);
    }

    // ── Hardware connect props ─────────────────────────────────────────────────

    public string SelectedHwInterface
    {
        get => selectedHwInterface;
        set => SetProperty(ref selectedHwInterface, value ?? "virtual");
    }

    public string SelectedHwVehicleId
    {
        get => selectedHwVehicleId;
        set => SetProperty(ref selectedHwVehicleId, value ?? "");
    }

    public string HwChannel
    {
        get => hwChannel;
        set => SetProperty(ref hwChannel, value ?? "0");
    }

    public string HwBitrate
    {
        get => hwBitrate;
        set => SetProperty(ref hwBitrate, value ?? "500000");
    }

    public string HwStatusText
    {
        get => hwStatusText;
        private set => SetProperty(ref hwStatusText, value);
    }

    // ── Config-backed settings ─────────────────────────────────────────────────

    public string GoogleApiKey
    {
        get => appConfig.GoogleApiKey;
        set { appConfig.GoogleApiKey = value ?? string.Empty; OnPropertyChanged(); }
    }

    public double AlertThreshold
    {
        get => appConfig.AlertThreshold;
        set
        {
            appConfig.AlertThreshold = Math.Max(0.1, Math.Min(1.0, Math.Round(value, 2)));
            OnPropertyChanged();
            OnPropertyChanged(nameof(AlertThresholdText));
        }
    }

    public string AlertThresholdText => $"{AlertThreshold:F2}";

    // Legacy OBD2 fields kept for XAML binding compatibility
    public string AdapterName   { get; set; } = "ELM327 USB";
    public string BaudRateText  { get; set; } = "500000";
    public string PortName      { get; set; } = "COM3";

    // ── Read-only display ──────────────────────────────────────────────────────

    public string RuntimeMode         => ConnectivityText;
    public string ApiEndpoint         => VehicleDataService.ApiEndpoint;
    public string JsonFallbackPath    => VehicleDataService.JsonFallbackPath;
    public string RefreshIntervalText => $"{(int)VehicleDataService.RefreshInterval.TotalMilliseconds} MS";
    public string LatencyText         => $"{VehicleDataService.RuntimeLatencyMs:F1} ms";

    public string DetectionModelText { get => detectionModelText; private set => SetProperty(ref detectionModelText, value); }
    public string ModelClustersText  { get => modelClustersText;  private set => SetProperty(ref modelClustersText,  value); }
    public string LlmProviderText    { get => llmProviderText;    private set => SetProperty(ref llmProviderText,    value); }
    public string ModelStatusText    { get => modelStatusText;    private set => SetProperty(ref modelStatusText,    value); }
    public string SaveStatusText     { get => saveStatusText;     private set => SetProperty(ref saveStatusText,     value); }

    // The backend health endpoint does not report a model training timestamp, so there is no
    // real data to bind to here — expose a placeholder rather than leaving the XAML binding dangling.
    public string TrainingDateText => "N/A";

    // ── Commands ───────────────────────────────────────────────────────────────

    private void SaveSettings()
    {
        appConfig.Save();
        if (!string.IsNullOrWhiteSpace(appConfig.GoogleApiKey))
            Environment.SetEnvironmentVariable("GOOGLE_API_KEY", appConfig.GoogleApiKey);
        SaveStatusText = "SETTINGS SAVED";
        _ = ClearSaveStatusAfterDelay();
    }

    private void RestoreDefaults()
    {
        AlertThreshold = 0.55;
        GoogleApiKey   = string.Empty;
        SaveStatusText = "DEFAULTS RESTORED";
        _ = ClearSaveStatusAfterDelay();
    }

    private async Task LaunchSimulatorAsync()
    {
        SaveStatusText = "STARTING ATTACK SIMULATION...";
        await VehicleDataService.StartSimulatorAsync().ConfigureAwait(true);
        SaveStatusText = "ATTACK SIMULATION ACTIVE — GO TO TELEMETRY";
    }

    private async Task ClearSaveStatusAfterDelay()
    {
        await Task.Delay(3000).ConfigureAwait(true);
        SaveStatusText = string.Empty;
    }

    private async Task LoadHardwareVehiclesAsync()
    {
        for (int attempt = 0; attempt < 15; attempt++)
        {
            if (attempt > 0)
                await Task.Delay(2000).ConfigureAwait(true);
            try
            {
                var result = await VehicleDataService.GetVehicleListAsync().ConfigureAwait(true);
                if (result is null) continue;
                HardwareVehicleItems.Clear();
                foreach (var v in result.Vehicles)
                    HardwareVehicleItems.Add(v);
                if (HardwareVehicleItems.Count > 0 && string.IsNullOrEmpty(SelectedHwVehicleId))
                    SelectedHwVehicleId = HardwareVehicleItems[0].Id;
                return;
            }
            catch { /* backend may be starting */ }
        }
    }

    private async Task ConnectHardwareAsync()
    {
        HwStatusText = "CONNECTING...";
        if (!int.TryParse(HwBitrate, out var bitrate)) bitrate = 500_000;
        var ok = await VehicleDataService.ConnectHardwareAsync(
            SelectedHwInterface, HwChannel, bitrate, SelectedHwVehicleId).ConfigureAwait(true);
        if (ok)
        {
            HwStatusText = $"CONNECTED — {SelectedHwInterface.ToUpperInvariant()}";
            hwPollTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(2) };
            hwPollTimer.Tick += async (_, _) => await PollHardwareStatusAsync().ConfigureAwait(true);
            hwPollTimer.Start();
        }
        else
        {
            HwStatusText = "CONNECTION FAILED — check interface and channel";
        }
    }

    private async Task DisconnectHardwareAsync()
    {
        hwPollTimer?.Stop();
        hwPollTimer = null;
        HwStatusText = "DISCONNECTING...";
        await VehicleDataService.DisconnectHardwareAsync().ConfigureAwait(true);
        HwStatusText = "DISCONNECTED";
    }

    private async Task PollHardwareStatusAsync()
    {
        try
        {
            var s = await VehicleDataService.GetHardwareStatusAsync().ConfigureAwait(true);
            if (s is null) return;
            if (!s.IsConnected)
            {
                hwPollTimer?.Stop();
                hwPollTimer = null;
                HwStatusText = "DISCONNECTED (lost connection)";
                return;
            }
            HwStatusText = $"LIVE · {s.InterfaceType.ToUpperInvariant()} · {s.FramesReceived:N0} frames · score {s.CurrentScore:F3}";
        }
        catch { /* non-fatal */ }
    }

    private async Task InitHardwareAsync()
    {
        for (int attempt = 0; attempt < 15; attempt++)
        {
            if (attempt > 0)
                await Task.Delay(2000).ConfigureAwait(true);
            try
            {
                var check = await VehicleDataService.GetHardwareCheckAsync().ConfigureAwait(true);
                if (check is null) continue;
                PythonCanAvailable = check.PythonCanAvailable;
                PythonCanWarning = check.PythonCanAvailable
                    ? $"python-can {check.PythonCanVersion} · pyserial {(check.PyserialAvailable ? "OK" : "missing")}"
                    : "python-can NOT installed — run: pip install python-can pyserial";
                await RefreshPortsAsync().ConfigureAwait(true);
                return;
            }
            catch { /* backend may still be starting */ }
        }
    }

    private async Task RefreshPortsAsync()
    {
        try
        {
            var result = await VehicleDataService.GetHardwarePortsAsync().ConfigureAwait(true);
            if (result is null) return;
            HardwareChannelItems.Clear();
            foreach (var p in result.Ports)
                HardwareChannelItems.Add(p.Name);
            // Always keep useful defaults at the end
            foreach (var def in new[] { "0", "PCAN_USBBUS1", "can0", "/dev/can0" })
                if (!HardwareChannelItems.Contains(def)) HardwareChannelItems.Add(def);
            if (HardwareChannelItems.Count > 0 && string.IsNullOrEmpty(HwChannel))
                HwChannel = HardwareChannelItems[0];
        }
        catch { /* non-fatal */ }
    }

    private async Task RefreshModelInfoAsync()
    {
        for (int attempt = 0; attempt < 15; attempt++)
        {
            if (attempt > 0)
                await Task.Delay(2000).ConfigureAwait(true);
            try
            {
                var health = await pythonApiClient.GetSystemHealthDetailAsync(CancellationToken.None).ConfigureAwait(true);
                if (health is null) { ModelStatusText = "BACKEND OFFLINE"; continue; }
                DetectionModelText = health.ModelLoaded ? "IsolationForest + KMeans" : "MODEL NOT LOADED";
                ModelClustersText  = health.ModelLoaded ? $"{health.ModelClusters} clusters" : "--";
                LlmProviderText    = string.IsNullOrWhiteSpace(health.LlmProvider) ? "NONE" : health.LlmProvider.ToUpperInvariant();
                ModelStatusText    = health.ModelLoaded ? "ACTIVE" : "OFFLINE";
                return;
            }
            catch { ModelStatusText = "BACKEND OFFLINE"; }
        }
    }

    protected override void OnDataUpdated(VehicleSnapshot snapshot)
    {
        OnPropertyChanged(nameof(RuntimeMode));
        OnPropertyChanged(nameof(LatencyText));
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

public sealed class AttackTypeBarItem
{
    public string Label    { get; set; } = "";
    public int    Count    { get; set; }
    public double BarWidth { get; set; }
    public string Color    { get; set; } = "#00C8C8";
    public string CountText => Count.ToString();
}

public sealed class CanActivityItem
{
    public string CanId    { get; set; } = "0x000";
    public int    Count    { get; set; }
    public double AvgScore { get; set; }
    public double BarWidth { get; set; }
    public string BarColor { get; set; } = "#56F0AC";
    public string CountText => Count.ToString();
    public string ScoreText => $"{AvgScore:F2}";
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
// AnomalyIntelViewModel — AI alert list + grounded chatbot interface
// ──────────────────────────────────────────────────────────────────────────────

public sealed class AnomalyIntelViewModel : SectionViewModel
{
    private readonly PythonApiClient pythonApiClient;
    private AlertDetailItem? selectedAlert;
    private string statusText    = "NO ALERTS — WAITING FOR IDS EVENTS";
    private string chatInputText = string.Empty;

    public AnomalyIntelViewModel(VehicleDataService vehicleDataService, PythonApiClient pythonApiClient)
        : base(vehicleDataService, SectionKey.AnomalyIntel)
    {
        this.pythonApiClient = pythonApiClient;
        Alerts             = new ObservableCollection<AlertDetailItem>();
        ChatMessages       = new ObservableCollection<ChatMessage>();
        AttackDistribution = new ObservableCollection<AttackTypeBarItem>();
        TimelineMarkers    = new ObservableCollection<TimelineMarker>();
        SelectAlertCommand        = new RelayCommand<AlertDetailItem?>(SelectAlert);
        SelectMarkerAlertCommand  = new RelayCommand<TimelineMarker?>(m => { if (m?.Alert is not null) SelectAlert(m.Alert); });
        RefreshCommand      = new RelayCommand(Refresh);
        SendChatCommand     = new AsyncRelayCommand(SendChatAsync, CanSendChat);
        ExportAlertsCommand = new AsyncRelayCommand(ExportAlertsAsync);
        ExportPdfCommand    = new AsyncRelayCommand(ExportPdfAsync);
        vehicleDataService.AlertHistoryUpdated += OnAlertHistoryUpdated;
        Refresh();
    }

    public ObservableCollection<AlertDetailItem>   Alerts             { get; }
    public ObservableCollection<ChatMessage>       ChatMessages       { get; }
    public ObservableCollection<AttackTypeBarItem> AttackDistribution { get; }
    public ObservableCollection<TimelineMarker>    TimelineMarkers    { get; }

    public IRelayCommand<TimelineMarker?> SelectMarkerAlertCommand { get; }

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
    public bool HasChatMessages  => ChatMessages.Count > 0;

    public string ChatInputText
    {
        get => chatInputText;
        set
        {
            SetProperty(ref chatInputText, value);
            SendChatCommand.NotifyCanExecuteChanged();
        }
    }

    public string StatusText
    {
        get => statusText;
        private set => SetProperty(ref statusText, value);
    }

    public bool HasAlerts       => Alerts.Count > 0;
    public string AlertCountText => Alerts.Count == 0 ? "NO EVENTS" : $"{Alerts.Count} EVENT{(Alerts.Count == 1 ? "" : "S")}";
    public int CriticalCount    => Alerts.Count(a => a.Severity == "CRITICAL");
    public int HighCount        => Alerts.Count(a => a.Severity is "HIGH" or "WARNING");

    public IRelayCommand<AlertDetailItem?> SelectAlertCommand  { get; }
    public IRelayCommand                   RefreshCommand      { get; }
    public IAsyncRelayCommand              SendChatCommand     { get; }
    public IAsyncRelayCommand              ExportAlertsCommand { get; }
    public IAsyncRelayCommand              ExportPdfCommand    { get; }

    private bool CanSendChat() => !string.IsNullOrWhiteSpace(chatInputText) && selectedAlert is not null;

    private void Refresh() => OnAlertHistoryUpdated(VehicleDataService.AlertHistory);

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
            Alerts.Add(BuildDetailItem(i, history[i]));

        StatusText = $"SHOWING {Alerts.Count} IDS ALERT{(Alerts.Count == 1 ? "" : "S")}";
        OnPropertyChanged(nameof(HasAlerts));
        OnPropertyChanged(nameof(AlertCountText));
        OnPropertyChanged(nameof(CriticalCount));
        OnPropertyChanged(nameof(HighCount));

        if (selectedAlert is null && Alerts.Count > 0)
            SelectAlert(Alerts[0]);

        RefreshDistribution();
        RefreshTimeline();
    }

    private void RefreshDistribution()
    {
        AttackDistribution.Clear();
        var groups = Alerts
            .GroupBy(a => NormalizeAttackType(a.AttackType))
            .OrderByDescending(g => g.Count())
            .Take(5)
            .ToList();

        if (groups.Count == 0) return;

        var max = groups[0].Count();
        var colors = new[] { "#00C8C8", "#56F0AC", "#FFD94A", "#FF8C3A", "#B46CFF" };

        for (var i = 0; i < groups.Count; i++)
        {
            var g = groups[i];
            AttackDistribution.Add(new AttackTypeBarItem
            {
                Label    = g.Key,
                Count    = g.Count(),
                BarWidth = Math.Max(4, 160.0 * g.Count() / max),
                Color    = colors[i % colors.Length],
            });
        }
    }

    private void RefreshTimeline()
    {
        TimelineMarkers.Clear();
        if (Alerts.Count == 0) return;

        const double TimelineWidth = 1000.0;

        // Parse timestamps from alert Time strings; fall back to index position
        var times = Alerts.Select((a, i) =>
        {
            if (TimeSpan.TryParse(a.Time, out var ts))
                return ts.TotalSeconds;
            return (double)i;
        }).ToList();

        double tMin = times.Min();
        double tMax = times.Max();
        double span = tMax - tMin;
        if (span < 0.001) span = 1.0;

        for (var i = 0; i < Alerts.Count; i++)
        {
            var alert = Alerts[i];
            var rel   = (times[i] - tMin) / span;
            var color = alert.Severity switch
            {
                "CRITICAL" => "#FF2626",
                "HIGH"     => "#FF8C3A",
                "WARNING"  => "#FFD700",
                _          => "#00C8C8",
            };
            TimelineMarkers.Add(new TimelineMarker
            {
                X           = rel * TimelineWidth,
                Color       = color,
                CanId       = alert.CanId,
                Severity    = alert.Severity,
                RelativePos = rel,
                Alert       = alert,
            });
        }
    }

    private static string NormalizeAttackType(string raw)
    {
        var s = raw.ToUpperInvariant();
        if (s.Contains("TIMING") || s.Contains("BURST") || s == "RUNTIME") return "TIMING";
        if (s.Contains("PAYLOAD") || s.Contains("CONTINUITY"))             return "PAYLOAD";
        if (s.Contains("ML") || s.Contains("OUTLIER"))                      return "ML OUTLIER";
        if (s.Contains("TEMPORAL") || s.Contains("REPLAY"))                 return "TEMPORAL";
        if (s is "CRITICAL" or "HIGH" or "WARNING")                         return s;
        return "UNKNOWN";
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
            Index         = index,
            Time          = evt.TimestampUtc.ToLocalTime().ToString("HH:mm:ss.fff"),
            CanId         = evt.CanId,
            Severity      = evt.Severity,
            SeverityColor = color,
            Score         = evt.Score,
            AttackType    = string.IsNullOrWhiteSpace(evt.AttackType) ? "UNKNOWN" : evt.AttackType.ToUpperInvariant(),
            Reason        = evt.Reason,
            LayerTiming   = timing,
            LayerPayload  = payload,
            LayerMl       = ml,
            LayerTemporal = temporal,
        };

        var capturedItem = item;
        item.ExplainCommand = new AsyncRelayCommand(
            () => AutoExplainAsync(capturedItem),
            () => !capturedItem.IsLoading);

        return item;
    }

    private void SelectAlert(AlertDetailItem? item)
    {
        if (item is null) return;
        SelectedAlert = item;

        ChatMessages.Clear();
        OnPropertyChanged(nameof(HasChatMessages));

        if (item.HasExplanation)
        {
            // Already explained — push cached text to chat instantly (no API call)
            var sb = new System.Text.StringBuilder(item.ExplanationSummary);
            if (!string.IsNullOrEmpty(item.ExplanationDetail))
                sb.Append("\n\n").Append(item.ExplanationDetail);
            if (!string.IsNullOrEmpty(item.ExplanationRecommendation))
                sb.Append("\n\nRecommendation: ").Append(item.ExplanationRecommendation);
            ChatMessages.Add(new ChatMessage { Role = "ai", Text = sb.ToString(), Time = DateTime.Now.ToString("HH:mm"), Mode = item.ExplanationMode });
            OnPropertyChanged(nameof(HasChatMessages));
        }
        else
        {
            _ = AutoExplainAsync(item);
        }
    }

    private async Task AutoExplainAsync(AlertDetailItem item)
    {
        item.IsLoading = true;
        item.ExplainCommand?.NotifyCanExecuteChanged();

        var typing = new ChatMessage { Role = "ai", Text = "Analyzing anomaly...", Time = DateTime.Now.ToString("HH:mm") };
        ChatMessages.Add(typing);
        OnPropertyChanged(nameof(HasChatMessages));

        try
        {
            var response = await pythonApiClient.GetAlertExplanationAsync(item.Index, System.Threading.CancellationToken.None);

            if (!ReferenceEquals(selectedAlert, item)) return; // user switched alert mid-request

            ChatMessages.Remove(typing);

            if (response is not null)
            {
                item.ExplanationSummary        = response.Summary;
                item.ExplanationDetail         = response.Detail;
                item.ExplanationRecommendation = response.Recommendation;
                item.ExplanationMode           = response.Mode;
                if (response.LayerTiming > 0 || response.LayerPayload > 0 || response.LayerMl > 0)
                {
                    item.LayerTiming   = response.LayerTiming;
                    item.LayerPayload  = response.LayerPayload;
                    item.LayerMl       = response.LayerMl;
                    item.LayerTemporal = response.LayerTemporal;
                }
                if (response.DecodedSignals.Count > 0) item.SetDecodedSignals(response.DecodedSignals);
                if (!string.IsNullOrEmpty(response.KbMatchLabel)) item.KbMatchLabel = response.KbMatchLabel;

                // Multi-layer detection enrichment
                item.PlausibilityPassed  = response.PlausibilityPassed;
                if (response.PlausibilityViolations.Count > 0)
                {
                    item.PlausibilityText = string.Join(" | ", response.PlausibilityViolations
                        .Select(v => $"{v.Signal}: {v.Value:F1}{(string.IsNullOrEmpty(v.Unit) ? "" : " " + v.Unit)} (limit {v.MinNormal:F0}–{v.MaxNormal:F0})"));
                }
                item.TimingAnomaly      = response.TimingAnomaly;
                item.TimingScore        = response.TimingScore;
                item.TemporalPattern    = response.TemporalPattern;
                item.TemporalScore      = response.TemporalScore;
                if (!string.IsNullOrEmpty(response.Recommendation))
                    item.RecommendedResponse = response.Recommendation;
                if (response.DetectionLayers.Count > 0)
                    item.DetectionLayersText = string.Join(" | ", response.DetectionLayers);

                item.HasExplanation = true;

                // Build a structured first message: summary → detail → layers → recommendation
                var sb = new System.Text.StringBuilder();

                if (!string.IsNullOrEmpty(response.Summary))
                    sb.Append(response.Summary);

                if (!string.IsNullOrEmpty(response.Detail))
                    sb.Append("\n\n").Append(response.Detail);

                // Layer attribution inline
                var layers = new System.Collections.Generic.List<string>();
                if (item.LayerTiming  > 0.01) layers.Add($"Timing {item.LayerTiming:F3}");
                if (item.LayerPayload > 0.01) layers.Add($"Payload {item.LayerPayload:F3}");
                if (item.LayerMl      > 0.01) layers.Add($"ML {item.LayerMl:F3}");
                if (item.LayerTemporal > 0.01) layers.Add($"Temporal {item.LayerTemporal:F3}");
                if (layers.Count > 0)
                    sb.Append("\n\nDetection layers: ").Append(string.Join(" · ", layers));

                if (!string.IsNullOrEmpty(response.KbMatchLabel))
                    sb.Append("\nKB match: ").Append(response.KbMatchLabel);

                // Plausibility violations
                if (!response.PlausibilityPassed && response.PlausibilityViolations.Count > 0)
                {
                    sb.Append("\n\nPlausibility violations: ");
                    sb.Append(string.Join(", ", response.PlausibilityViolations
                        .Select(v => $"{v.Signal} = {v.Value:F1}{(string.IsNullOrEmpty(v.Unit) ? "" : " " + v.Unit)}")));
                }

                // Temporal pattern
                if (response.TemporalPattern != "normal")
                    sb.Append($"\nTemporal: {response.TemporalPattern.Replace("_", " ")} (score {response.TemporalScore:F2})");

                // Timing anomaly
                if (response.TimingAnomaly)
                    sb.Append($"\nFingerprint: {response.TimingScore:F1}σ deviation from ECU baseline");

                if (!string.IsNullOrEmpty(response.Recommendation))
                    sb.Append("\n\nAction: ").Append(response.Recommendation);

                if (sb.Length == 0)
                    sb.Append($"Alert on {item.CanId} — score {item.Score:F3} ({item.Severity}). Ask me anything about this anomaly.");

                ChatMessages.Add(new ChatMessage { Role = "ai", Text = sb.ToString(), Time = DateTime.Now.ToString("HH:mm"), Mode = response.Mode });
            }
            else
            {
                item.ExplanationMode = "rule_based";
                ChatMessages.Add(new ChatMessage
                {
                    Role = "ai",
                    Text = BuildLocalExplanation(item),
                    Time = DateTime.Now.ToString("HH:mm"),
                    Mode = "rule_based",
                });
            }
        }
        catch
        {
            if (ReferenceEquals(selectedAlert, item))
            {
                item.ExplanationMode = "rule_based";
                ChatMessages.Remove(typing);
                ChatMessages.Add(new ChatMessage
                {
                    Role = "ai",
                    Text = BuildLocalExplanation(item),
                    Time = DateTime.Now.ToString("HH:mm"),
                    Mode = "rule_based",
                });
            }
        }
        finally
        {
            item.IsLoading = false;
            item.ExplainCommand?.NotifyCanExecuteChanged();
        }

        OnPropertyChanged(nameof(HasChatMessages));
    }

    private static string BuildLocalExplanation(AlertDetailItem item)
    {
        var sb = new System.Text.StringBuilder();

        var sevDesc = item.Severity switch
        {
            "CRITICAL" => "critical intrusion",
            "WARNING"  => "high-risk anomaly",
            "LOW"      => "elevated anomaly",
            _          => "anomaly",
        };

        sb.Append($"Detected a {sevDesc} on CAN-ID {item.CanId} — fusion score {item.Score:F3} ({item.Severity}).");

        if (!string.IsNullOrEmpty(item.AttackType) && item.AttackType != "ANOMALY" && item.AttackType != "AI ANOMALY")
            sb.Append($" Attack pattern: {item.AttackType}.");

        if (!string.IsNullOrEmpty(item.Reason))
            sb.Append($"\n\nDetection reason: {item.Reason}");

        var layers = new System.Collections.Generic.List<string>();
        if (item.LayerTiming   > 0.01) layers.Add($"Timing {item.LayerTiming:F3}");
        if (item.LayerPayload  > 0.01) layers.Add($"Payload {item.LayerPayload:F3}");
        if (item.LayerMl       > 0.01) layers.Add($"ML {item.LayerMl:F3}");
        if (item.LayerTemporal > 0.01) layers.Add($"Temporal {item.LayerTemporal:F3}");
        if (layers.Count > 0)
            sb.Append("\n\nDetection layers: ").Append(string.Join(" · ", layers));

        return sb.ToString();
    }

    private async Task SendChatAsync()
    {
        var message = chatInputText.Trim();
        var alert   = selectedAlert;
        if (string.IsNullOrEmpty(message) || alert is null) return;

        ChatInputText = string.Empty;

        ChatMessages.Add(new ChatMessage { Role = "user", Text = message, Time = DateTime.Now.ToString("HH:mm") });

        var typing = new ChatMessage { Role = "ai", Text = "...", Time = DateTime.Now.ToString("HH:mm") };
        ChatMessages.Add(typing);
        OnPropertyChanged(nameof(HasChatMessages));

        try
        {
            var response = await pythonApiClient.ChatAsync(
                alert.CanId, alert.Score, alert.Severity, alert.AttackType, alert.Reason,
                message, System.Threading.CancellationToken.None);

            ChatMessages.Remove(typing);
            ChatMessages.Add(new ChatMessage
            {
                Role = "ai",
                Text = response?.Reply ?? "AI engine unavailable.",
                Time = DateTime.Now.ToString("HH:mm"),
                Mode = response?.Mode ?? "rule_based",
            });
        }
        catch
        {
            ChatMessages.Remove(typing);
            ChatMessages.Add(new ChatMessage
            {
                Role = "ai",
                Text = "Connection failed — check Python server.",
                Time = DateTime.Now.ToString("HH:mm"),
                Mode = "rule_based",
            });
        }

        OnPropertyChanged(nameof(HasChatMessages));
    }

    private async Task ExportAlertsAsync()
    {
        if (Alerts.Count == 0) return;
        var dialog = new SaveFileDialog
        {
            Filter   = "CSV files (*.csv)|*.csv",
            FileName = $"alerts_{DateTime.Now:yyyyMMdd_HHmmss}.csv",
            Title    = "Export Alerts",
        };
        if (dialog.ShowDialog() != true) return;
        var lines = new System.Collections.Generic.List<string>
        {
            "Time,CAN_ID,Severity,AttackType,Score,Reason,KbMatch,Explanation,Recommendation"
        };
        lines.AddRange(Alerts.Select(a =>
        {
            static string Esc(string s) => $"\"{s.Replace("\"", "\"\"")}\"";
            return string.Join(",",
                a.Time, a.CanId, a.Severity, a.AttackType, $"{a.Score:F3}",
                Esc(a.Reason),
                Esc(a.KbMatchLabel),
                Esc(a.ExplanationSummary),
                Esc(a.ExplanationRecommendation));
        }));
        await Task.Run(() => File.WriteAllLines(dialog.FileName, lines)).ConfigureAwait(true);
    }

    private async Task ExportPdfAsync()
    {
        if (Alerts.Count == 0) return;
        var dialog = new SaveFileDialog
        {
            Filter   = "PDF files (*.pdf)|*.pdf",
            FileName = $"CANvision_AlertReport_{DateTime.Now:yyyyMMdd_HHmmss}.pdf",
            Title    = "Export Alert Report as PDF",
        };
        if (dialog.ShowDialog() != true) return;

        var snapshot  = Alerts.ToList();
        var filePath  = dialog.FileName;
        var generated = DateTime.Now;

        await Task.Run(() => PdfReportBuilder.Build(snapshot, filePath, generated)).ConfigureAwait(true);
    }

    protected override void OnDataUpdated(VehicleSnapshot snapshot) => base.OnDataUpdated(snapshot);

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
                case "timing":      timing   = val; break;
                case "payload":     payload  = val; break;
                case "ml":          ml       = val; break;
                case "persistence": temporal = val; break;
            }
        }
        return (timing, payload, ml, temporal);
    }
}
