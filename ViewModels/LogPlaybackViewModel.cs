using System.Globalization;
using System;
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

public sealed class LogPlaybackViewModel : SectionViewModel
{
    private string playbackMode = "STOPPED";
    private double playbackSpeed = 1;
    private readonly DispatcherTimer playbackTimer;
    private readonly CanLogImportService canLogImportService;
    private readonly AppLogger logger;
    private readonly ModelSelectionService modelSelection;
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
    // Detection threshold as a fraction of the plot height, measured from the top.
    // Normal traffic tops out at density*0.62, so 0.28 from the top (score 0.72)
    // sits above it: only real ML detections cross the line.
    private const double ScoreThresholdFromTop = 0.28;
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
    private string _offlineStatusText = "";
    private string _offlineSessionId = "";
    private bool _isOfflineDone = false;
    private OfflineSummaryResponse? _offlineResult;

    public LogPlaybackViewModel(VehicleDataService vehicleDataService, CanLogImportService canLogImportService, AppLogger logger, ModelSelectionService modelSelection)
        : base(vehicleDataService, SectionKey.LogPlayback)
    {
        this.modelSelection = modelSelection;
        modelSelection.SelectionChanged += _ =>
        {
            OnPropertyChanged(nameof(SelectedVehicleId));
            OnPropertyChanged(nameof(SelectedVehicleNameText));
        };
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

    /// <summary>The shared vehicle / AI model selection, for the screen's selector.</summary>
    public ModelSelectionService ModelSelection => modelSelection;

    // The shared vehicle / AI model selection (ModelSelectionService). The backend replay
    // (replay_runner --vehicle) and the MF4 offline analysis both receive it as their vehicle id.
    public string SelectedVehicleId
    {
        get => modelSelection.SelectedModelId;
        set => modelSelection.Select(value);
    }

    public string SelectedVehicleNameText => modelSelection.SelectedModel.Name;

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
            // Same frame as the CURSOR readout, placed by the same mapping as every marker.
            if (CurrentPacket is null) return 0;
            return ReplayTimeline.Fraction(CurrentPacket.Frame.RelativeTimestampSeconds, _fileStart, _fileEnd) * 100.0;
        }
    }
    public double PlaybackCursorLeft => ReplayProgressPercent / 100.0 * TimelineCanvasWidth;
    public string PlaybackPositionText => playbackData.Count == 0 ? "0 / 0" : $"{Math.Min(currentFrameIndex + 1, playbackData.Count):N0} / {playbackData.Count:N0}";
    public string CurrentTimestampText => CurrentPacket is null ? "--:--:--.---" : CurrentPacket.Frame.TimestampUtc.ToLocalTime().ToString("HH:mm:ss.fff");
    public string TotalTimestampText => playbackData.Count == 0 ? "--:--:--.---" : playbackData[playbackData.Count - 1].Frame.TimestampUtc.ToLocalTime().ToString("HH:mm:ss.fff");
    public string SyncStateText => playbackData.Count == 0 ? "NO CAPTURE" : "LOCKED";
    public string TimelineScaleText => _fileEnd > _fileStart
        ? ReplayTimeline.FormatOffset(_fileEnd - _fileStart, _fileEnd - _fileStart)
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
    public string NormalFramesPercentText => TotalFrames == 0 ? "100.0%" : (Math.Max(0, TotalFrames - TotalDetections) * 100.0 / TotalFrames).ToString("F1", CultureInfo.InvariantCulture) + "%";
    // Numeric form of NormalFramesPercentText, for driving the anomaly-distribution
    // ring's arc (StrokeDashArray needs a raw 0-100 double, not a formatted string).
    // Previously that ring was wired to ReplayProgressPercent by mistake, so it
    // visually showed replay progress instead of the actual normal/anomaly split.
    public double NormalFramesPercent => TotalFrames == 0 ? 100.0 : Math.Max(0, TotalFrames - TotalDetections) * 100.0 / TotalFrames;
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

    /// <summary>
    /// The same blended detection waveform as <see cref="DetectionScorePoints"/>, as plain
    /// 0-1 values for the LiveCharts2 trend. Presentation passthrough - a fresh snapshot is
    /// published whenever the points are rebuilt; nothing is computed here.
    /// </summary>
    public IReadOnlyList<double> DetectionScoreValues { get; private set; } = Array.Empty<double>();

    /// <summary>Threshold in the same 0-1 space as <see cref="DetectionScoreValues"/>.</summary>
    public double DetectionThresholdValue => 1.0 - ScoreThresholdFromTop;
    public string DetectionThresholdText => DetectionThresholdValue.ToString("F2");
    public string DetectionScoreCeilingText => "/ 1.00";
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
            return first != null ? $"{first.AnomalyScore:F2}" : "0.00";
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
        var vehicleId = SelectedVehicleId;
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
        // The capture span, not the sum of replay delays: delays are floored at 1 ms,
        // so frames sharing a timestamp inflated it (see ReplayTimeline).
        sessionDurationText = playbackData.Count < 2
            ? "00:00:00"
            : ReplayTimeline.FormatDuration(_fileEnd - _fileStart);
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
            TimelineMarkers.Insert(0, new ForensicTimelineMarker("Playback", PlaybackCursorLeft, 16, "CURSOR", "#00C8C8"));
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

        TimelineMarkers.Add(new ForensicTimelineMarker("Playback", PlaybackCursorLeft, 16, "CURSOR", "#00C8C8"));

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

    // Places a frame by its capture timestamp - the same basis as the cursor and the axis.
    private double BuildTimelineX(int index)
    {
        if (playbackData.Count < 2) return 0;
        var i = Math.Max(0, Math.Min(index, playbackData.Count - 1));
        return ReplayTimeline.ToX(playbackData[i].Frame.RelativeTimestampSeconds, _fileStart, _fileEnd, TimelineCanvasWidth);
    }

    // ratio is 0-1 of the session's duration, so the 25% tick reads 25% of the time.
    private string FormatTimelineOffset(double ratio)
    {
        if (playbackData.Count < 2 || _fileEnd <= _fileStart) return "00:00";
        var span = _fileEnd - _fileStart;
        return ReplayTimeline.FormatOffset(ratio * span, span);
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
            var b = (int)(ReplayTimeline.Fraction(playbackData[i].Frame.RelativeTimestampSeconds, _fileStart, _fileEnd) * (ScorePlotW - 1));
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

        DetectionScoreValues = (double[])blended.Clone();
        OnPropertyChanged(nameof(DetectionScoreValues));

        // Threshold sits above the max normal-traffic level (density*0.62 <= 0.62, y>=45)
        DetectionThresholdPoints.Clear();
        DetectionThresholdPoints.Add(new System.Windows.Point(0, ScorePlotH * ScoreThresholdFromTop));
        DetectionThresholdPoints.Add(new System.Windows.Point(ScorePlotW, ScorePlotH * ScoreThresholdFromTop));

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
        OnPropertyChanged(nameof(NormalFramesPercent));
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

