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

    private readonly PythonApiClient? pythonApiClient;
    private readonly ModelSelectionService? modelSelection;
    private int discoveryGeneration;
    private SignalDiscoveryResponse? discovery;
    // Every DBC-decoded channel of the loaded capture (the cards show the first four).
    private IReadOnlyList<DiscoveredChannel> decodedChannels = Array.Empty<DiscoveredChannel>();
    private const int CardChannels = 4;
    private const int MonitorChannels = 16;

    public TelemetryViewModel(VehicleDataService vehicleDataService, CanLogImportService canLogImportService,
                              PythonApiClient? pythonApiClient = null, ModelSelectionService? modelSelection = null)
        : base(vehicleDataService, SectionKey.Telemetry)
    {
        this.canLogImportService = canLogImportService;
        this.pythonApiClient = pythonApiClient;
        this.modelSelection = modelSelection;
        DiscoveredChannels = new ObservableCollection<DiscoveredChannelItem>();
        if (modelSelection is not null)
            modelSelection.SelectionChanged += _ => { var pending = DiscoverSignalsAsync(); };
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
    public string ConnectionStateText => string.Equals(Snapshot.Source, "python-api", StringComparison.OrdinalIgnoreCase) ? "CONNECTED"
        : ShowsCapture ? "CAPTURE" : "LOCAL FALLBACK";
    public string LiveStateText => ConnectionStateText == "CONNECTED" ? "LIVE"
        : string.Equals(Snapshot.Source, "log-playback", StringComparison.OrdinalIgnoreCase) || VehicleDataService.TotalReplayFrames > 0
            ? "CAPTURE" : "OFFLINE";
    public string PacketsPerSecondText => $"{VehicleDataService.RuntimeFps:F1}";
    public string LastEventTimestamp => Snapshot.UpdatedAt.ToLocalTime().ToString("HH:mm:ss");
    public string ReplayStatusText => VehicleDataService.ReplayProgressPercent >= 100 ? "COMPLETE" : VehicleDataService.ReplayProgressPercent > 0 ? "RUNNING" : "IDLE";
    public string RuntimeStateText => $"{ConnectionStateText} / {ReplayStatusText}";
    public string DetectionConfidenceText => VehicleDataService.DetectionConfidence > 0 ? $"{VehicleDataService.DetectionConfidence:F1}%" : "--";
    public string ActiveModelName => ModelText;
    // ── Signal channels found in the loaded capture (POST /api/signals/discover) ──
    // With a DBC for the selected vehicle these are decoded signals; without one they
    // are raw payload bytes, labelled as undecoded. Live mode keeps the fixed tiles.
    public ObservableCollection<DiscoveredChannelItem> DiscoveredChannels { get; }
    public bool HasDiscoveredChannels => DiscoveredChannels.Count > 0;
    public bool ShowFixedChannels => !HasDiscoveredChannels;
    public string SignalSourceText => discovery is null ? "SPEED · SOC · TEMP · VOLTAGE"
        : discovery.Decoder == "dbc" ? $"DECODED · {discovery.Profile.ToUpperInvariant()} DBC"
        : discovery.DbcAvailable ? $"RAW BYTES · {discovery.Profile.ToUpperInvariant()} DBC DECODES NO VARYING SIGNAL"
        : $"RAW BYTES · NO DBC FOR {(string.IsNullOrWhiteSpace(discovery.ModelId) ? "GENERAL" : discovery.ModelId.ToUpperInvariant())}";
    public string SignalWindowText => discovery is null ? "LAST 80 SAMPLES" : "80 SAMPLES ACROSS CAPTURE";
    public string SignalSourceToolTip => discovery?.Reason ?? "Live values decoded by the backend.";

    private async Task DiscoverSignalsAsync()
    {
        var generation = ++discoveryGeneration;
        var path = VehicleDataService.ReplaySourcePath;
        SignalDiscoveryResponse? result = null;
        if (pythonApiClient is not null && !string.IsNullOrWhiteSpace(path) && VehicleDataService.TotalReplayFrames > 0)
        {
            var model = modelSelection?.SelectedModelId ?? string.Empty;
            if (string.Equals(model, ModelSelectionService.GeneralId, StringComparison.OrdinalIgnoreCase)) model = string.Empty;
            result = await pythonApiClient.DiscoverSignalsAsync(path!, model, MonitorChannels, System.Threading.CancellationToken.None);
        }
        if (generation != discoveryGeneration) return;      // a newer capture or model superseded this one

        discovery = result;
        DiscoveredChannels.Clear();
        decodedChannels = result?.Channels.Where(c => c.Decoded).ToList() ?? (IReadOnlyList<DiscoveredChannel>)Array.Empty<DiscoveredChannel>();
        if (result is not null)
        {
            for (var i = 0; i < Math.Min(CardChannels, result.Channels.Count); i++)
                DiscoveredChannels.Add(new DiscoveredChannelItem(result.Channels[i], i));
        }
        RefreshSignalRows();
        OnPropertyChanged(nameof(HasDiscoveredChannels));
        OnPropertyChanged(nameof(ShowFixedChannels));
        OnPropertyChanged(nameof(SignalSourceText));
        OnPropertyChanged(nameof(SignalWindowText));
        OnPropertyChanged(nameof(SignalSourceToolTip));
    }

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
    public string PacketRateText => Snapshot.Frequency > 0 ? $"{Snapshot.Frequency:F1} Hz" : "--";
    public string SampleRateText => Snapshot.Frequency > 0 ? $"{Snapshot.Frequency:F1} Hz" : "--";
    public string LatencyText => $"{Math.Max(0, VehicleDataService.RuntimeLatencyMs):F1} ms";
    public string ReplayFpsText => $"{Math.Max(0, VehicleDataService.RuntimeFps):F1}";
    public string DroppedFramesText => VehicleDataService.LoadedReplayPackets is { Count: > 0 } ? "0 (0.0%)" : "--";
    public string InferenceHealthText => VehicleDataService.DetectedAttackType == "ANALYZING..." ? "ANALYZING" : "READY";
    public string ReplayLatencyText => LatencyText;
    public string PacketTimelineCaption => VehicleDataService.TotalReplayFrames > 0
        ? $"{VehicleDataService.ProcessedReplayFrames:N0}/{VehicleDataService.TotalReplayFrames:N0} frames"
        : StreamHealthLine;
    // Read-only numeric snapshots of the rolling channel histories (last 80
    // samples each) for the LiveCharts2 traces. Same data the PointCollections
    // below are drawn from; a fresh array per read so bindings refresh.
    public double[] SpeedHistory => speedHistory.ToArray();
    public double[] VoltageHistory => voltageHistory.ToArray();
    public double[] CurrentHistory => currentHistory.ToArray();
    public double[] MotorTempHistory => motorTempHistory.ToArray();
    public double[] PacketRateHistory => packetRateHistory.ToArray();
    public double[] SocHistory => socHistory.ToArray();
    /// <summary>0-100 numeric twin of RuntimeReplayProgressText, for the progress bar.</summary>
    public double ReplayProgressPercent => VehicleDataService.ReplayProgressPercent;

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
    // RuntimeFps is the app's processing rate (frames analysed or polled per second),
    // not the rate the bus carried; for a recording the two differ several-fold.
    public string PacketsPerSecondTelemetryStateText => VehicleDataService.RuntimeFps > 0 ? "Processing Rate" : "Offline";
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
            // A capture that finished playing is not a degraded stream: its state is the
            // result of its analysis.
            if (ShowsCapture)
                return VehicleDataService.CriticalAlerts > 0 ? "CRITICAL"
                     : VehicleDataService.TotalAlerts > 0 ? "THREAT DETECTED" : "MONITORING";
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
        "CRITICAL"          => "#FF4D5E",
        "THREAT DETECTED"   => "#FFB245",
        "ELEVATED RISK"     => "#FFD94A",
        "ANALYZING"         => "#7EF7E4",
        "MONITORING"        => "#35E6A1",
        "BASELINING"        => "#96B4FF",
        _                   => "#FFB245",
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

    public string CanTrafficVolumeText => latestSignals.Count > 0 ? $"{latestSignals.Count} signals"
        : SignalRows.Count > 0 ? $"{SignalRows.Count} signals · capture DBC" : "No decoded signals";
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

    /// <summary>
    /// Brings the live signal monitor up to date.
    ///
    /// Rows are matched to signals by CAN id and name and updated where they
    /// stand; only a signal appearing or disappearing changes the collection
    /// itself. Rebuilding the whole list on each refresh - twice a second while
    /// a session runs - made the table flash and blank between ticks.
    /// </summary>
    private void RefreshSignalRows()
    {
        // Live decoded signals first; an offline capture sends no frames to the live stream,
        // so its DBC-decoded values come from the capture itself, at the replay position.
        var displaySignals = latestSignals.Count > 0 ? latestSignals : CaptureDecodedSignals();

        if (displaySignals.Count == 0)
        {
            if (SignalRows.Count > 0) SignalRows.Clear();
            if (ActiveSignals.Count > 0) ActiveSignals.Clear();
            OnPropertyChanged(nameof(CanTrafficVolumeText));
            return;
        }

        var ordered = displaySignals.OrderBy(s => s.CanId).ThenBy(s => s.Name).ToList();

        // Drop rows whose signal is no longer in the stream.
        var live = new HashSet<string>(ordered.Select(s => $"0x{s.CanId:X3}|{s.Name.ToUpperInvariant()}"));
        for (var i = SignalRows.Count - 1; i >= 0; i--)
            if (!live.Contains($"{SignalRows[i].CanId}|{SignalRows[i].Name}"))
                SignalRows.RemoveAt(i);

        var byKey = SignalRows.ToDictionary(r => $"{r.CanId}|{r.Name}");

        for (var i = 0; i < ordered.Count; i++)
        {
            var signal = ordered[i];
            var canId = $"0x{signal.CanId:X3}";
            var name = signal.Name.ToUpperInvariant();
            var trend = BuildTrendPoints(GetSignalHistory(signal), 72, 18);

            if (byKey.TryGetValue($"{canId}|{name}", out var row))
            {
                row.Update(
                    $"{signal.Value:F2}",
                    BuildSignalStatus(signal),
                    Snapshot.Frequency,
                    Snapshot.TimeDiff,
                    trend,
                    BuildSignalStatusBrush(signal));

                // Keep the rows in the same order as the signals.
                var at = SignalRows.IndexOf(row);
                if (at != i) SignalRows.Move(at, i);
                continue;
            }

            SignalRows.Insert(i, new SignalItem(
                canId,
                name,
                $"{signal.Value:F2}",
                signal.Unit,
                BuildSignalStatus(signal),
                Snapshot.Frequency,
                Snapshot.TimeDiff,
                trend,
                BuildSignalStatusBrush(signal),
                BuildCanIdBrush(signal.CanId)));
        }

        ActiveSignals.Clear();
        foreach (var signal in displaySignals
                     .OrderByDescending(item => Math.Abs(item.Value))
                     .Take(5))
        {
            ActiveSignals.Add(new SignalLegendItem(signal.Name.ToUpperInvariant(), "#00FFFF"));
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
        VehicleDataService.LoadReplayPackets(Path.GetFileName(dialog.FileName), packets, dialog.FileName);
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
            lines.Add(FormattableString.Invariant($"{s.TimestampUtc:o},0x{s.CanId:X3},{s.FeatureKey},{s.Name},{s.Value:F4},{s.Unit},{(s.OutOfRange ? "1" : "0")}"));
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
        OnPropertyChanged(nameof(ReplayProgressPercent));
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
        OnPropertyChanged(nameof(SpeedHistory));
        OnPropertyChanged(nameof(VoltageHistory));
        OnPropertyChanged(nameof(CurrentHistory));
        OnPropertyChanged(nameof(MotorTempHistory));
        OnPropertyChanged(nameof(PacketRateHistory));
        OnPropertyChanged(nameof(SocHistory));
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
        RefreshCanActivityFromAlerts();
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
        OnPropertyChanged(nameof(ReplayProgressPercent));
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

    // A capture played in the app sends nothing to the backend's live buffer, which fed
    // this panel, so it said "no flagged CAN IDs" beside 339 alerts. For a capture the
    // panel counts the analysis alerts per identifier instead.
    private void RefreshCanActivityFromAlerts()
    {
        if (!ShowsCapture)
            return;
        _canIdStats.Clear();
        foreach (var alert in VehicleDataService.AlertHistory)
        {
            _canIdStats[alert.CanId] = _canIdStats.TryGetValue(alert.CanId, out var s)
                ? (s.Count + 1, s.ScoreSum + alert.Score)
                : (1, alert.Score);
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
        _ = DiscoverSignalsAsync();

        OnPropertyChanged(nameof(ReplayNameText));
        OnPropertyChanged(nameof(HasReplayLoaded));
        OnPropertyChanged(nameof(SessionDurationText));
        OnPropertyChanged(nameof(RuntimeReplayFramesText));
        OnPropertyChanged(nameof(RuntimeReplayProgressText));
        OnPropertyChanged(nameof(ReplayProgressPercent));
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

    /// <summary>
    /// DBC-decoded values of the loaded capture for the LIVE SIGNAL MONITOR, when no live stream
    /// feeds it. Without this, a recording fully decoded by its DBC showed "No decoded signals"
    /// under channels that were decoded. Each value is the channel's sample at the replay cursor,
    /// or its last value in the capture before a replay starts. Nothing is invented: a capture
    /// without a DBC, or whose DBC decodes no varying signal, still shows no rows.
    /// </summary>
    private IReadOnlyList<DecodedSignal> CaptureDecodedSignals()
    {
        if (decodedChannels.Count == 0 || VehicleDataService.TotalReplayFrames == 0)
            return Array.Empty<DecodedSignal>();

        var progress = VehicleDataService.ReplayProgressPercent;
        var duration = discovery?.DurationS ?? 0;
        var now = DateTime.UtcNow;
        var signals = new List<DecodedSignal>(decodedChannels.Count);
        foreach (var channel in decodedChannels)
        {
            var upTo = channel.Values.Count - 1;
            if (progress > 0 && progress < 100 && duration > 0 && channel.Times.Count == channel.Values.Count)
            {
                var cursor = progress / 100.0 * duration;
                upTo = Math.Max(0, channel.Times.FindLastIndex(t => t <= cursor));
            }
            var signal = new DecodedSignal
            {
                Name = channel.Label,
                Value = upTo >= 0 ? channel.Values[upTo] : channel.Last,
                Unit = channel.Unit,
                CanId = channel.CanId,
                FeatureKey = "DBC",
                TimestampUtc = now,
            };
            signalValueHistory[SignalHistoryKey(signal)] = channel.Values.Take(upTo + 1).ToList();
            signals.Add(signal);
        }
        return signals;
    }

    private string BuildSignalStatus(DecodedSignal signal)
    {
        if (IsStreamFrozen && latestSignals.Count > 0)
        {
            return "HELD";
        }

        if (latestSignals.Count == 0)
        {
            if (signal.FeatureKey == "DBC" && decodedChannels.Count > 0)
                return "REPLAY";
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
            "REPLAY" => "#00C8C8",
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

/// <summary>One discovered channel as a Telemetry tile / channel row.</summary>
public sealed class DiscoveredChannelItem
{
    private static readonly string[] Strokes = { "#2FF0D6", "#B07BFF", "#7EF7E4", "#FFB245" };

    public DiscoveredChannelItem(DiscoveredChannel channel, int index)
    {
        Channel = channel;
        StrokeHex = Strokes[index % Strokes.Length];
        Values = channel.Values.ToList();
    }

    public DiscoveredChannel Channel { get; }
    public string StrokeHex { get; }
    public List<double> Values { get; }
    public string Title => Channel.Decoded ? Channel.Label.ToUpperInvariant() : Channel.Label;
    public string UnitText => Channel.Decoded ? (string.IsNullOrWhiteSpace(Channel.Unit) ? "--" : Channel.Unit.ToUpperInvariant()) : "RAW";
    public string ValueText => Channel.Decoded
        ? $"{Channel.Last:0.##}{(string.IsNullOrWhiteSpace(Channel.Unit) ? "" : " " + Channel.Unit)}"
        : $"0x{(int)Channel.Last:X2}";
    public string MetaText => Channel.Decoded ? $"DBC · 0x{Channel.CanId:X} · {RateText}" : $"UNDECODED · {RateText}";
    public string RangeText => Channel.Decoded
        ? $"range {Channel.Min:0.##} … {Channel.Max:0.##}"
        : $"range 0x{(int)Channel.Min:X2} … 0x{(int)Channel.Max:X2} · {Channel.Distinct} values";
    public string ToolTip => $"{Channel.Label}: {Channel.Samples:N0} samples, {RateText}, {RangeText}. Last value in the capture shown."
                             + (Channel.Decoded ? "" : " Raw payload byte: no DBC defines what it means.");
    private string RateText => Channel.RateHz >= 1 ? $"{Channel.RateHz:0} HZ" : Channel.RateHz > 0 ? $"{Channel.RateHz:0.##} HZ" : "-- HZ";
}
