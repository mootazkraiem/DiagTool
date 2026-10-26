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

public sealed class DashboardViewModel : SectionViewModel
{
    private readonly List<double> rollingScores = new();
    private const int RollingScoreCapacity = 120; // 60 s at 500 ms per tick
    private double captureCursorSeconds = double.NaN;

    private readonly PythonApiClient? pythonApiClient;

    public DashboardViewModel(VehicleDataService vehicleDataService, ModelSelectionService? modelSelection = null,
                              PythonApiClient? pythonApiClient = null)
        : base(vehicleDataService, SectionKey.Dashboard)
    {
        this.modelSelection = modelSelection;
        this.pythonApiClient = pythonApiClient;
        DatasetFacts = new ObservableCollection<DatasetFactItem>();
        DatasetParagraphs = new ObservableCollection<string>();
        OpenDatasetCardCommand = new AsyncRelayCommand(OpenDatasetCardAsync);
        CloseDatasetCardCommand = new RelayCommand(() => IsDatasetCardOpen = false);
        if (modelSelection is not null)
            modelSelection.SelectionChanged += _ => OnPropertyChanged(nameof(ActiveModelName));
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
        vehicleDataService.ReplayLoaded += () =>
        {
            rollingScores.Clear();
            captureCursorSeconds = double.NaN;
            LiveFrames.Clear();
        };
        vehicleDataService.LiveFramesUpdated += OnLiveFramesUpdated;
        vehicleDataService.PlaybackFramePublished += OnPlaybackFrame;

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
    public string DetectionConfidenceText => VehicleDataService.DetectionConfidence > 0 ? $"{VehicleDataService.DetectionConfidence:F1}%" : "--";
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
    // The selected vehicle / AI model and its status (was the fixed text "IDS-STATE-MODEL").
    public string ActiveModelName => modelSelection?.SelectedModel is { } m ? $"{m.ModelLabel} · {m.KindText}" : "--";
    private readonly ModelSelectionService? modelSelection;
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
    // LIVE: backend stream; CAPTURE: a loaded log is on screen (the backend may well be
    // connected - "OFFLINE" read as if it were not); OFFLINE: neither.
    public string LiveStateText => ConnectionStateText == "CONNECTED" ? "LIVE" : ShowsCapture ? "CAPTURE" : "OFFLINE";
    public string SystemNameText => UnitNameText;
    public string LastSyncSummaryText => ConnectionStateText == "CONNECTED" ? "ALL SYSTEMS SYNCED" : ShowsCapture ? "CAPTURE LOADED" : "SYNC PENDING";
    // Alerts of a loaded recording are session alerts, not live ones; "LIVE" only while a bus is connected.
    public string AlertsPanelTitle => ConnectionStateText == "CONNECTED" ? "LIVE ALERTS" : "SESSION ALERTS";
    public System.Windows.Media.Brush StatusGlowBrush =>
        ConnectionStateText == "CONNECTED"
            ? new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(0, 200, 200))
            : new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(80, 100, 100));
    public string LastEventTimestamp => Snapshot.UpdatedAt.ToLocalTime().ToString("HH:mm:ss");
    // Capture: replayed frames carry no score of their own and the fusion score only moves
    // in a live session (it read 0.0 beside CRITICAL), so the score fields show the highest
    // score among the frames the analysis flagged - the score behind the state shown.
    private double DisplayScore => ShowsCapture && VehicleDataService.AlertHistory.Count > 0
        ? PeakFlaggedScore
        : VehicleDataService.CurrentAnomalyScore;
    public string ScoreTileLabel => ShowsCapture ? "PEAK SCORE" : "FUSION SCORE";
    public string AnomalyScoreText => ShowsCapture
        ? (DisplayScore > 0 ? $"{DisplayScore:F2}" : "0.00")
        : VehicleDataService.CurrentAnomalyScore > 0 ? $"{VehicleDataService.CurrentAnomalyScore:F1}" : "0.0";
    public string TopAnomalousCanId => !string.IsNullOrEmpty(VehicleDataService.TopSuspiciousCanId) ? VehicleDataService.TopSuspiciousCanId : "N/A";
    public int TotalFrames => VehicleDataService.TotalReplayFrames;
    public string ReplayElapsedText => SessionTimerText;
    public string RuntimeStateText => $"{ConnectionStateText} / {ReplayStatusText}";
    public string StatusSubtitleText => $"SOC {BatteryText}  VOLT {VoltageText}";
    /// <summary>0-100 numeric twin of AnomalyConfidenceText, for the confidence bar.</summary>
    public double DetectionConfidenceValue => VehicleDataService.DetectionConfidence;
    public string AnomalyConfidenceText => VehicleDataService.DetectionConfidence > 0 ? $"{VehicleDataService.DetectionConfidence:F1}%" : "--";
    public string PacketsAnalyzedText => VehicleDataService.ProcessedReplayFrames.ToString("N0");
    public string DetectionsTodayText => VehicleDataService.TotalAlerts.ToString("N0");
    public string ActiveThreatsText => OperationalStateText is "THREAT DETECTED" or "CRITICAL" ? "1" : "0";
    public string CurrentThreatText => VehicleDataService.TotalAlerts > 0 ? VehicleDataService.DetectedAttackType : "System Nominal";
    public string ThreatSeverityText => OperationalStateText == "CRITICAL" ? "CRITICAL" : VehicleDataService.TotalAlerts > 0 ? "HIGH" : "NORMAL";
    public string AffectedCanIdsText => string.IsNullOrWhiteSpace(VehicleDataService.TopSuspiciousCanId) ? "None" : VehicleDataService.TopSuspiciousCanId;
    public string AttackTypeText => VehicleDataService.TotalAlerts > 0 ? VehicleDataService.DetectedAttackType : "None";
    public string LiveAlertsCountText => $"{VehicleDataService.TotalAlerts:N0}";
    // Flagged share of the SCORED frames when an offline analysis ran (alerts merge
    // bursts; unresolved frames are neither flagged nor normal), stated by DetectionRateBasisText.
    public string DetectionRateBasisText => VehicleDataService.FlaggedFractionBasisText;
    public string DetectionRateText => VehicleDataService.FlaggedFraction is { } fraction
        ? (fraction * 100.0).ToString("F1", System.Globalization.CultureInfo.InvariantCulture) + "%"
        : VehicleDataService.ProcessedReplayFrames <= 0 ? "--" : $"{VehicleDataService.TotalAlerts * 100.0 / Math.Max(1, VehicleDataService.ProcessedReplayFrames):F1}%";
    // The pair behind DetectionRateText: flagged / scored frames of the analysis, else
    // (live) alerts / frames processed. It used to show alerts / frames PLAYED during a
    // replay ("339 / 264"), which is not what the percentage is taken from.
    public string DetectionRateFractionText => VehicleDataService.FlaggedFraction is not null
        ? $"{VehicleDataService.FlaggedFrames:N0} / {VehicleDataService.ScoredFrames:N0}"
        : $"{VehicleDataService.TotalAlerts:N0} / {VehicleDataService.ProcessedReplayFrames:N0}";
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
        "CRITICAL"          => "#FF4D5E",
        "THREAT DETECTED"   => "#FFB245",
        "ELEVATED RISK"     => "#FFD94A",
        "ANALYZING"         => "#7EF7E4",
        "MONITORING"        => "#2FF0D6",
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
        "CRITICAL"          => $"CRITICAL · {VehicleDataService.DetectedAttackType} · SCORE {DisplayScore:F3}",
        "THREAT DETECTED"   => $"PATTERN: {VehicleDataService.DetectedAttackType}",
        "ELEVATED RISK"     => $"RISK SCORE {DisplayScore:F3} · WATCH ACTIVE",
        "ANALYZING"         => $"SCORE {VehicleDataService.CurrentAnomalyScore:F3} — BASELINE COMPARISON",
        "MONITORING"        => "ALL CHANNELS NOMINAL",
        "BASELINING"        => "ESTABLISHING TRAFFIC BASELINE...",
        "READY"             => "DATASET LOADED — START ANALYSIS",
        _                   => "OFFLINE — IMPORT DATASET FROM HOME",
    };
    // ─────────────────────────────────────────────────────────────────────────

    private void PushRollingScore(double score)
    {
        rollingScores.Add(score);
        if (rollingScores.Count > RollingScoreCapacity)
            rollingScores.RemoveAt(0);
    }

    private double? CaptureTickScore()
    {
        // While the analysis runs, the cursor follows the backend reading the file, not
        // a playback the user started; the trend waits for Play.
        if (VehicleDataService.AppState == AppState.Analyzing)
            return null;
        var packets = VehicleDataService.LoadedReplayPackets;
        if (packets is null || packets.Count == 0)
            return null;
        var index = Math.Min(packets.Count - 1, Math.Max(0, VehicleDataService.ProcessedReplayFrames - 1));
        var now = packets[index].Frame.RelativeTimestampSeconds;
        var previous = double.IsNaN(captureCursorSeconds) || now < captureCursorSeconds ? now : captureCursorSeconds;
        captureCursorSeconds = now;
        if (now <= previous)
            return null;
        return VehicleDataService.AlertHistory
            .Where(a => a.RelativeSeconds > previous && a.RelativeSeconds <= now)
            .Select(a => a.Score)
            .DefaultIfEmpty(0)
            .Max();
    }

    // ── Dataset card: what the loaded capture is, in plain words ─────────────
    private bool isDatasetCardOpen;
    private string datasetTitleText = string.Empty;
    private string datasetSourceText = string.Empty;

    public bool IsDatasetCardOpen
    {
        get => isDatasetCardOpen;
        private set => SetProperty(ref isDatasetCardOpen, value);
    }

    public string DatasetTitleText
    {
        get => datasetTitleText;
        private set => SetProperty(ref datasetTitleText, value);
    }

    public string DatasetSourceText
    {
        get => datasetSourceText;
        private set => SetProperty(ref datasetSourceText, value);
    }

    public ObservableCollection<DatasetFactItem> DatasetFacts { get; }
    public ObservableCollection<string> DatasetParagraphs { get; }
    public IAsyncRelayCommand OpenDatasetCardCommand { get; }
    public IRelayCommand CloseDatasetCardCommand { get; }

    private async Task OpenDatasetCardAsync()
    {
        DatasetFacts.Clear();
        DatasetParagraphs.Clear();
        DatasetSourceText = string.Empty;
        IsDatasetCardOpen = true;

        var path = VehicleDataService.ReplaySourcePath;
        if (string.IsNullOrWhiteSpace(path) || VehicleDataService.TotalReplayFrames == 0)
        {
            DatasetTitleText = "No dataset loaded";
            DatasetParagraphs.Add(ConnectionStateText == "CONNECTED"
                ? "This is a live session: messages come straight from the CAN adapter, so there is no recorded file to describe."
                : "No recording is loaded yet. Import a CAN log from the Home screen and its description appears here.");
            return;
        }

        DatasetTitleText = System.IO.Path.GetFileName(path);
        DatasetParagraphs.Add("Reading the file…");
        var model = modelSelection?.SelectedModelId ?? string.Empty;
        var facts = pythonApiClient is null ? null
            : await pythonApiClient.DescribeDatasetAsync(path!, model, System.Threading.CancellationToken.None);

        DatasetParagraphs.Clear();
        if (facts is null)
        {
            DatasetParagraphs.Add("The backend could not read this file, so no description is available. Check that the Python backend is running.");
            return;
        }

        DatasetTitleText = DatasetCard.Title(facts);
        foreach (var item in DatasetCard.Facts(facts)) DatasetFacts.Add(item);
        foreach (var text in DatasetCard.Paragraphs(facts, GroundTruthLabels.FindFor(path) is not null)) DatasetParagraphs.Add(text);
        var folder = System.IO.Path.GetDirectoryName(path);
        var parent = folder is null ? null : System.IO.Path.GetFileName(System.IO.Path.GetDirectoryName(folder));
        DatasetSourceText = "SOURCE  " + string.Join(" / ", new[] { parent, facts.Folder, facts.FileName }
            .Where(s => !string.IsNullOrWhiteSpace(s)));
    }

    public string TrendWindowText => ShowsCapture ? "· FLAGGED FRAMES · 60 S" : "· 60 S WINDOW";

    protected override void OnDataUpdated(VehicleSnapshot snapshot)
    {
        base.OnDataUpdated(snapshot);

        // Keep a rolling 60-second window of scores for the chart. Live: the backend's
        // fusion score. Capture: replayed frames carry no score of their own, so each
        // tick plots the highest score among the flagged frames the playback cursor
        // passed since the last tick (0 = none flagged); a paused cursor adds nothing.
        var currentScore = VehicleDataService.CurrentAnomalyScore;
        if (ShowsCapture)
        {
            if (CaptureTickScore() is { } captureScore)
                PushRollingScore(captureScore);
        }
        else if (VehicleDataService.IsRunning || currentScore > 0)
        {
            PushRollingScore(currentScore);
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
        OnPropertyChanged(nameof(TrendWindowText));
        OnPropertyChanged(nameof(SystemNameText));
        OnPropertyChanged(nameof(LastSyncSummaryText));
        OnPropertyChanged(nameof(AlertsPanelTitle));
        OnPropertyChanged(nameof(StatusGlowBrush));
        OnPropertyChanged(nameof(LastEventTimestamp));
        OnPropertyChanged(nameof(AnomalyScoreText));
        OnPropertyChanged(nameof(TopAnomalousCanId));
        OnPropertyChanged(nameof(TotalFrames));
        OnPropertyChanged(nameof(ReplayElapsedText));
        OnPropertyChanged(nameof(RuntimeStateText));
        OnPropertyChanged(nameof(StatusSubtitleText));
        OnPropertyChanged(nameof(AnomalyConfidenceText));
        OnPropertyChanged(nameof(DetectionConfidenceValue));
        OnPropertyChanged(nameof(PacketsAnalyzedText));
        OnPropertyChanged(nameof(DetectionsTodayText));
        OnPropertyChanged(nameof(ActiveThreatsText));
        OnPropertyChanged(nameof(CurrentThreatText));
        OnPropertyChanged(nameof(ThreatSeverityText));
        OnPropertyChanged(nameof(AffectedCanIdsText));
        OnPropertyChanged(nameof(AttackTypeText));
        OnPropertyChanged(nameof(LiveAlertsCountText));
        OnPropertyChanged(nameof(DetectionRateText));
        OnPropertyChanged(nameof(DetectionRateFractionText));
        OnPropertyChanged(nameof(DetectionRateBasisText));
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
        OnPropertyChanged(nameof(DetectionConfidenceValue));
        OnPropertyChanged(nameof(PacketsAnalyzedText));
        OnPropertyChanged(nameof(DetectionsTodayText));
        OnPropertyChanged(nameof(ActiveThreatsText));
        OnPropertyChanged(nameof(CurrentThreatText));
        OnPropertyChanged(nameof(ThreatSeverityText));
        OnPropertyChanged(nameof(AffectedCanIdsText));
        OnPropertyChanged(nameof(AttackTypeText));
        OnPropertyChanged(nameof(LiveAlertsCountText));
        OnPropertyChanged(nameof(DetectionRateText));
        OnPropertyChanged(nameof(DetectionRateFractionText));
        OnPropertyChanged(nameof(DetectionRateBasisText));
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

    private DateTime lastPlaybackFrameUtc = DateTime.MinValue;

    // A capture playing in the app: newest frame first, 30 kept. Frames the model did not
    // flag carry no score ("--"); flagged ones show their score and severity.
    private void OnPlaybackFrame(PlaybackPacket packet)
    {
        lastPlaybackFrameUtc = DateTime.UtcNow;
        var score = packet.Anomalies.Count == 0 ? 0.0
            : packet.Anomalies.Max(a => a.SeverityScore > 0 ? a.SeverityScore / 100.0 : Math.Abs(a.AnomalyScore));
        var severity = packet.Anomalies.Count == 0 ? "NORMAL" : score >= 0.8 ? "CRITICAL" : score >= 0.55 ? "HIGH" : "WARNING";
        var data = packet.Frame.Data ?? Array.Empty<byte>();
        LiveFrames.Insert(0, new LiveFrameRow
        {
            Time     = packet.Frame.TimestampUtc.ToLocalTime().ToString("HH:mm:ss.fff"),
            CanId    = $"0x{packet.Frame.CanId:X3}",
            Bytes    = string.Join(" ", data.Select(b => b.ToString("X2"))),
            Score    = packet.Anomalies.Count == 0 ? "--" : $"{score:F2}",
            Severity = severity,
            SeverityColor = severity switch
            {
                "CRITICAL" => "#FF5050",
                "HIGH"     => "#FF8C3A",
                "WARNING"  => "#FFD94A",
                _          => "#56F0AC",
            },
        });
        while (LiveFrames.Count > 30)
            LiveFrames.RemoveAt(LiveFrames.Count - 1);
    }

    private void OnLiveFramesUpdated(IReadOnlyList<LiveSignalItem> items)
    {
        // While a capture plays in the app its frames own the monitor; the backend's
        // buffer would otherwise replace them every 2.5 s with a different stream.
        if ((DateTime.UtcNow - lastPlaybackFrameUtc).TotalSeconds < 3)
            return;
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
        DashboardTopKpis.Add(new AnalysisKpiItem(ScoreTileLabel, AnomalyScoreText, OperationalStateText, anomalyTrend, "#2FF0D6"));
        DashboardTopKpis.Add(new AnalysisKpiItem(ConnectionStateText == "CONNECTED" ? "LIVE FPS" : "PROCESSING FPS", RuntimeFpsText, "FRAMES / SEC", fpsTrend, "#2FF0D6"));
        DashboardTopKpis.Add(new AnalysisKpiItem("ACTIVE THREATS", ActiveThreatsText, "CURRENT", alertTrend, "#FFB245"));
        DashboardTopKpis.Add(new AnalysisKpiItem("CRITICAL ALERTS", CriticalAlertsText, "IN SESSION", alertTrend, "#FF4D5E"));
        DashboardTopKpis.Add(new AnalysisKpiItem("FRAMES", PacketsAnalyzedText, "ANALYZED", frameTrend, "#DBE9E7"));
        DashboardTopKpis.Add(new AnalysisKpiItem("LATENCY", LatencyMsText, "ROUNDTRIP", fpsTrend, "#FFB245"));

        // Previously repeated 5 of the top strip's 6 values here verbatim
        // (FUSION SCORE, ACTIVE THREATS, CRITICAL ALERTS, LIVE FPS, LATENCY) —
        // same numbers, twice, on one screen. Keeping only the 3 values that
        // don't already appear in DashboardTopKpis above.
        DashboardBottomKpis.Clear();
        DashboardBottomKpis.Add(new AnalysisKpiItem("TOTAL ALERTS", TotalAlertsText, "SESSION", alertTrend, "#FF8C3A"));
        DashboardBottomKpis.Add(new AnalysisKpiItem("DETECTION RATE", DetectionRateText, "SESSION", alertTrend, "#B46CFF"));
        DashboardBottomKpis.Add(new AnalysisKpiItem("PIPELINE", PipelineHealthText, "HEALTH", fpsTrend, "#56F0AC"));

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

        // Until the window has two real ticks the chart stays flat. It used to fall back
        // to the list of every alert score, drawn as if it were the last 60 seconds.
        var chartValues = rollingScores.Count > 1
            ? rollingScores.ToList()
            : new List<double> { 0.0, 0.0 };
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

