using System.Windows.Threading;
using CANvision.Native.Models;
using CommunityToolkit.Mvvm.ComponentModel;
using System.Linq;
using System.Threading;

namespace CANvision.Native.Services;

public sealed class VehicleDataService : ObservableObject
{
    private readonly PythonApiClient pythonApiClient;
    private readonly AppLogger logger;
    private readonly DispatcherTimer refreshTimer;
    private readonly Dispatcher dispatcher;
    private readonly object sync = new();
    private VehicleSnapshot currentSnapshot = VehicleSnapshot.Default();
    private IReadOnlyList<CanAnomaly> currentAnomalies = Array.Empty<CanAnomaly>();
    private IReadOnlyList<DecodedSignal> currentSignals = Array.Empty<DecodedSignal>();
    private bool isRefreshing;
    private int fallbackFrameCounter;
    private int lastLiveAlertCount;
    private bool liveAlertBootstrapped; // true after first tick establishes baseline
    private int signalPollCounter;

    // Replay runtime state
    private string replayName = "NO REPLAY";
    private IReadOnlyList<PlaybackPacket>? loadedReplayPackets;
    private double runtimeLatencyMs;
    private double runtimeFps;
    private double replayProgressPercent;
    private int processedReplayFrames;
    private int totalReplayFrames;

    // Global analysis lifecycle state
    private AppState appState = AppState.NoDataset;

    // ML backend replay analysis state
    private string mlAnalysisState = "IDLE"; // IDLE | QUEUED | ANALYZING | COMPLETE | ERROR

    // IDS analysis runtime state
    private string detectedAttackType = "NONE";
    private double detectionConfidence;
    private double currentAnomalyScore;
    private double averageAnomalyScore;
    private double maxAnomalyScore;
    private int sessionScoreCount;
    private double sessionScoreSum;
    private string topSuspiciousCanId = "--";
    private int totalAlerts;
    private int criticalAlerts;
    private int warningAlerts;
    private IReadOnlyList<RuntimeAlertEvent> alertHistory = Array.Empty<RuntimeAlertEvent>();

    public event Action<VehicleSnapshot>? DataUpdated;
    public event Action<IReadOnlyList<CanAnomaly>>? AnomaliesUpdated;
    public event Action<IReadOnlyList<DecodedSignal>>? SignalsUpdated;
    public event Action? ReplayRuntimeUpdated;
    public event Action<IReadOnlyList<RuntimeAlertEvent>>? AlertHistoryUpdated;
    public event Action<IReadOnlyList<LiveSignalItem>>? LiveFramesUpdated;
    public event Action? ReplayLoaded;
    public event Action<AppState>? AppStateChanged;

    public bool IsRunning { get; private set; }

    public AppState AppState
    {
        get { lock (sync) { return appState; } }
    }

    public void SetAppState(AppState state)
    {
        lock (sync) { appState = state; }
        dispatcher.BeginInvoke(() => AppStateChanged?.Invoke(state));
    }

    public VehicleDataService(PythonApiClient pythonApiClient, AppLogger logger)
    {
        this.pythonApiClient = pythonApiClient;
        this.logger = logger;
        dispatcher = Dispatcher.CurrentDispatcher;
        refreshTimer = new DispatcherTimer(DispatcherPriority.Background, dispatcher)
        {
            Interval = TimeSpan.FromMilliseconds(500),
        };
        refreshTimer.Tick += OnRefreshTick;
    }

    // ── Properties ────────────────────────────────────────────────────────────

    public VehicleSnapshot CurrentSnapshot
    {
        get { lock (sync) { return currentSnapshot; } }
        private set { lock (sync) { currentSnapshot = value; } }
    }

    public IReadOnlyList<CanAnomaly> CurrentAnomalies
    {
        get { lock (sync) { return currentAnomalies; } }
        private set { lock (sync) { currentAnomalies = value; } }
    }

    public IReadOnlyList<DecodedSignal> CurrentSignals
    {
        get { lock (sync) { return currentSignals; } }
        private set { lock (sync) { currentSignals = value; } }
    }

    public string ReplayName
    {
        get { lock (sync) { return replayName; } }
        private set { lock (sync) { replayName = value; } }
    }

    public IReadOnlyList<PlaybackPacket>? LoadedReplayPackets
    {
        get { lock (sync) { return loadedReplayPackets; } }
        private set { lock (sync) { loadedReplayPackets = value; } }
    }

    public double RuntimeLatencyMs  { get { lock (sync) { return runtimeLatencyMs; } } }
    public double RuntimeFps        { get { lock (sync) { return runtimeFps; } } }
    public double ReplayProgressPercent { get { lock (sync) { return replayProgressPercent; } } }
    public int    ProcessedReplayFrames { get { lock (sync) { return processedReplayFrames; } } }
    public int    TotalReplayFrames     { get { lock (sync) { return totalReplayFrames; } } }

    public string MlAnalysisState     { get { lock (sync) { return mlAnalysisState; } } }
    public string DetectedAttackType  { get { lock (sync) { return detectedAttackType; } } }
    public double DetectionConfidence { get { lock (sync) { return detectionConfidence; } } }
    public double CurrentAnomalyScore { get { lock (sync) { return currentAnomalyScore; } } }
    public double AverageAnomalyScore { get { lock (sync) { return averageAnomalyScore; } } }
    public double MaxAnomalyScore     { get { lock (sync) { return maxAnomalyScore; } } }
    public string TopSuspiciousCanId  { get { lock (sync) { return topSuspiciousCanId; } } }
    public int    TotalAlerts         { get { lock (sync) { return totalAlerts; } } }
    public int    CriticalAlerts      { get { lock (sync) { return criticalAlerts; } } }
    public int    WarningAlerts       { get { lock (sync) { return warningAlerts; } } }

    public IReadOnlyList<RuntimeAlertEvent> AlertHistory
    {
        get { lock (sync) { return alertHistory; } }
        private set { lock (sync) { alertHistory = value; } }
    }

    // Config / diagnostics
    public string ApiEndpoint     => pythonApiClient.ApiBase;
    public string JsonFallbackPath => string.Empty;
    public TimeSpan RefreshInterval => refreshTimer.Interval;

    // ── Lifecycle ─────────────────────────────────────────────────────────────

    public void Start()
    {
        SetAppState(AppState.LiveSession);
        if (!refreshTimer.IsEnabled)
        {
            refreshTimer.Start();
            IsRunning = true;
        }
        logger.Info("[VDS] Start() called — live session started, polling active.");
    }

    public void Stop()
    {
        refreshTimer.Stop();
        IsRunning = false;
        logger.Info("[VDS] Stopped.");
    }

    public async Task StartSimulatorAsync()
    {
        await pythonApiClient.StartLiveSessionAsync(CancellationToken.None);
        logger.Info("[VDS] Live simulator started for inject-test mode.");
    }

    public async Task StopSimulatorAsync()
    {
        await pythonApiClient.StopLiveSessionAsync(CancellationToken.None);
        logger.Info("[VDS] Live simulator stopped.");
    }

    // ── Session recording ─────────────────────────────────────────────────────

    public bool   IsRecording         { get; private set; }
    public int    RecordingFrameCount  { get; private set; }
    public double RecordingElapsed     { get; private set; }
    public string RecordingOutputPath  { get; private set; } = string.Empty;

    public async Task<bool> StartRecordingAsync()
    {
        var result = await pythonApiClient.StartRecordingAsync(CancellationToken.None);
        if (result is null) return false;
        IsRecording        = true;
        RecordingFrameCount = 0;
        RecordingElapsed    = 0;
        RecordingOutputPath = result.OutputPath ?? string.Empty;
        return true;
    }

    public async Task<string?> StopRecordingAsync()
    {
        var result = await pythonApiClient.StopRecordingAsync(CancellationToken.None);
        IsRecording        = false;
        RecordingFrameCount = result?.FrameCount ?? RecordingFrameCount;
        RecordingOutputPath = result?.OutputPath ?? RecordingOutputPath;
        return RecordingOutputPath;
    }

    public async Task RefreshRecordStatusAsync()
    {
        var result = await pythonApiClient.GetRecordStatusAsync(CancellationToken.None);
        if (result is null) return;
        IsRecording         = result.IsRecording;
        RecordingFrameCount = result.FrameCount;
        RecordingElapsed    = result.ElapsedSeconds;
    }

    public async Task<SystemHealthDetailResponse?> GetSystemHealthDetailAsync()
        => await pythonApiClient.GetSystemHealthDetailAsync(CancellationToken.None);

    public async Task<SessionListResponse?> GetSessionListAsync()
        => await pythonApiClient.GetSessionListAsync(CancellationToken.None);

    // ── Vehicle profiles ──────────────────────────────────────────────────────

    public async Task<VehicleListResponse?> GetVehicleListAsync()
        => await pythonApiClient.GetVehicleListAsync(CancellationToken.None);

    // ── Offline session analysis ──────────────────────────────────────────────

    public async Task<OfflineAnalyzeStartResponse?> StartOfflineAnalysisAsync(string filePath, string vehicleId)
        => await pythonApiClient.StartOfflineAnalysisAsync(filePath, vehicleId, CancellationToken.None);

    public async Task<OfflineSessionStatus?> GetOfflineStatusAsync(string sessionId)
        => await pythonApiClient.GetOfflineStatusAsync(sessionId, CancellationToken.None);

    public async Task<OfflineSummaryResponse?> GetOfflineSummaryAsync(string sessionId)
        => await pythonApiClient.GetOfflineSummaryAsync(sessionId, CancellationToken.None);

    // ── Live hardware CAN interface ───────────────────────────────────────────

    public async Task<bool> ConnectHardwareAsync(string interfaceType, string channel, int bitrate, string vehicleId)
        => await pythonApiClient.ConnectHardwareAsync(interfaceType, channel, bitrate, vehicleId, CancellationToken.None);

    public async Task<bool> DisconnectHardwareAsync()
        => await pythonApiClient.DisconnectHardwareAsync(CancellationToken.None);

    public async Task<HardwareStatusResponse?> GetHardwareStatusAsync()
        => await pythonApiClient.GetHardwareStatusAsync(CancellationToken.None);

    public async Task<HardwarePortsResponse?> GetHardwarePortsAsync()
        => await pythonApiClient.GetHardwarePortsAsync(CancellationToken.None);

    public async Task<HardwareCheckResponse?> GetHardwareCheckAsync()
        => await pythonApiClient.GetHardwareCheckAsync(CancellationToken.None);

    // ── Replay management ─────────────────────────────────────────────────────

    public void LoadReplayPackets(string name, IReadOnlyList<PlaybackPacket> packets)
    {
        lock (sync)
        {
            replayName          = name;
            loadedReplayPackets = packets;
            totalReplayFrames   = packets.Count;
            processedReplayFrames = 0;
            replayProgressPercent = 0;
        }

        dispatcher.BeginInvoke(() => ReplayLoaded?.Invoke());
        logger.Info($"[VDS] Replay loaded: {name} ({packets.Count} packets)");
    }

    public async Task TriggerBackendReplayAsync(string filePath)
    {
        lock (sync) { mlAnalysisState = "QUEUED"; }
        try
        {
            var result = await pythonApiClient.StartReplayAsync(filePath, 0, CancellationToken.None);
            lock (sync) { mlAnalysisState = result != null ? "ANALYZING" : "ERROR"; }
        }
        catch (Exception ex)
        {
            logger.Error("[VDS] TriggerBackendReplayAsync failed.", ex);
            lock (sync) { mlAnalysisState = "ERROR"; }
        }
    }

    public void PublishPlaybackPacket(PlaybackPacket packet)
    {
        var snap = packet.Snapshot;
        var anomalies = packet.Anomalies;
        var signals = packet.Signals;

        lock (sync)
        {
            currentSnapshot  = snap;
            currentAnomalies = anomalies;
            currentSignals   = signals;
        }

        dispatcher.BeginInvoke(() =>
        {
            DataUpdated?.Invoke(snap);
            SignalsUpdated?.Invoke(signals);
            if (anomalies.Count > 0)
                AnomaliesUpdated?.Invoke(anomalies);
        });
    }

    public void SetReplayCursor(int frameIndex)
    {
        lock (sync) { processedReplayFrames = Math.Max(0, frameIndex); }
    }

    public void UpdateReplayRuntime(int processed, int canId, double score, double fps, double latencyMs)
    {
        lock (sync)
        {
            processedReplayFrames = processed;
            replayProgressPercent = totalReplayFrames > 0
                ? processed * 100.0 / totalReplayFrames
                : 0;
            runtimeFps       = fps;
            runtimeLatencyMs = latencyMs;
            currentAnomalyScore = score;
            if (score > maxAnomalyScore) maxAnomalyScore = score;
            topSuspiciousCanId = $"0x{canId:X3}";

            if (score > 0)
            {
                sessionScoreCount++;
                sessionScoreSum += score;
                averageAnomalyScore = sessionScoreSum / sessionScoreCount;
            }
        }

        dispatcher.BeginInvoke(() => ReplayRuntimeUpdated?.Invoke());
    }

    public void BeginReplayAnalysis()
    {
        SetAppState(AppState.Analyzing);
        lock (sync)
        {
            detectedAttackType  = "ANALYZING...";
            detectionConfidence = 0;
            totalAlerts = criticalAlerts = warningAlerts = 0;
            alertHistory        = Array.Empty<RuntimeAlertEvent>();
            currentAnomalyScore = 0;
            averageAnomalyScore = 0;
            maxAnomalyScore     = 0;
            sessionScoreCount   = 0;
            sessionScoreSum     = 0;
            topSuspiciousCanId  = "--";
            runtimeFps          = 0;
            runtimeLatencyMs    = 0;
        }
    }

    public void CompleteReplayAnalysis(
        string attackType,
        double confidence,
        IReadOnlyList<RuntimeAlertEvent> alerts)
    {
        // Snapshot loaded packets under lock — build alert list outside the lock.
        IReadOnlyList<PlaybackPacket>? packets;
        lock (sync) { packets = loadedReplayPackets; }

        // Build canonical alert stream from per-frame ML annotations.
        var frameAlerts = new List<RuntimeAlertEvent>();
        if (packets is not null)
        {
            foreach (var packet in packets)
            {
                foreach (var anomaly in packet.Anomalies)
                {
                    if (anomaly.SeverityScore >= 30)
                    {
                        frameAlerts.Add(new RuntimeAlertEvent
                        {
                            TimestampUtc = anomaly.TimestampUtc,
                            CanId        = $"0x{anomaly.RelatedCanId:X3}",
                            Severity     = anomaly.Severity,
                            Score        = anomaly.SeverityScore / 100.0,
                            AttackType   = anomaly.Title,
                            Reason       = anomaly.Description,
                        });
                    }
                }
            }
        }

        // Merge with caller-supplied alerts; sort chronologically newest-first.
        var combined = frameAlerts
            .Concat(alerts)
            .OrderByDescending(a => a.TimestampUtc)
            .ToList();

        // Derive top suspicious CAN ID from the most-frequently-flagged frame ID.
        var topId = frameAlerts
            .GroupBy(a => a.CanId)
            .OrderByDescending(g => g.Count())
            .Select(g => g.Key)
            .FirstOrDefault();

        IReadOnlyList<RuntimeAlertEvent> finalHistory;
        lock (sync)
        {
            detectedAttackType  = attackType;
            detectionConfidence = confidence;
            alertHistory        = combined;
            totalAlerts         = combined.Count;
            criticalAlerts      = combined.Count(a => a.Severity == "CRITICAL");
            warningAlerts       = combined.Count(a => a.Severity == "WARNING");
            if (!string.IsNullOrEmpty(topId))
                topSuspiciousCanId = topId;
            finalHistory = alertHistory;
        }

        SetAppState(AppState.AnalysisComplete);
        dispatcher.BeginInvoke(() => AlertHistoryUpdated?.Invoke(finalHistory));
    }

    // ── External push (from Python API) ──────────────────────────────────────

    public void PublishExternalSnapshot(VehicleSnapshot snapshot)
    {
        lock (sync) { currentSnapshot = snapshot; }
        dispatcher.BeginInvoke(() => DataUpdated?.Invoke(snapshot));
    }

    public void UpdateAnomalies(IReadOnlyList<CanAnomaly> anomalies)
    {
        lock (sync) { currentAnomalies = anomalies; }
        dispatcher.BeginInvoke(() => AnomaliesUpdated?.Invoke(anomalies));
    }

    // ── Background refresh (live mode) ───────────────────────────────────────

    private async void OnRefreshTick(object? sender, EventArgs e)
    {
        if (isRefreshing) return;
        isRefreshing = true;
        try
        {
            var snap = await pythonApiClient.GetLatestSnapshotAsync(CancellationToken.None);
            if (snap is null) return;

            lock (sync) { currentSnapshot = snap; }
            DataUpdated?.Invoke(snap);

            fallbackFrameCounter++;

            // Drive live runtime stats so Dashboard score/FPS show real values.
            if (snap.AnomalyScore > 0 || snap.LiveFps > 0)
            {
                double fps = snap.LiveFps > 0 ? snap.LiveFps : 2.0;
                double latencyMs = 1000.0 / fps;
                UpdateReplayRuntime(fallbackFrameCounter, snap.LiveCanId, snap.AnomalyScore, fps, latencyMs);
            }

            // Pull live alerts only when no replay is active — prevents phantom alerts when no file is loaded.
            if (MlAnalysisState == "IDLE")
            {
                var alertResp = await pythonApiClient.GetLiveAlertsAsync(CancellationToken.None);
                if (alertResp?.Items is { } items)
                {
                if (!liveAlertBootstrapped)
                {
                    // First tick: establish baseline count so stale backend buffer doesn't flood the UI.
                    lastLiveAlertCount    = items.Count;
                    liveAlertBootstrapped = true;
                }
                else if (items.Count != lastLiveAlertCount)
                {
                    lastLiveAlertCount = items.Count;
                    var mapped = items
                        .Select(a => new RuntimeAlertEvent
                        {
                            TimestampUtc = DateTimeOffset.FromUnixTimeMilliseconds((long)(a.Timestamp * 1000)).UtcDateTime,
                            CanId        = a.CanId,
                            Severity     = a.Severity,
                            Score        = a.Score,
                            AttackType   = string.IsNullOrWhiteSpace(a.DominantDetectionLayer) ? "RUNTIME" : a.DominantDetectionLayer.ToUpperInvariant(),
                            Reason       = a.Reason,
                        })
                        .OrderByDescending(a => a.TimestampUtc)
                        .ToList();

                    IReadOnlyList<RuntimeAlertEvent> history;
                    lock (sync)
                    {
                        alertHistory    = mapped;
                        totalAlerts     = mapped.Count;
                        criticalAlerts  = mapped.Count(a => a.Severity == "CRITICAL");
                        warningAlerts   = mapped.Count(a => a.Severity == "HIGH" || a.Severity == "WARNING");
                        if (mapped.Count > 0)
                        {
                            topSuspiciousCanId  = mapped[0].CanId;
                            detectionConfidence = Math.Min(100.0, mapped[0].Score * 100.0);
                            detectedAttackType  = criticalAlerts > 0 ? "INTRUSION DETECTED"
                                                : warningAlerts > 0  ? "ELEVATED RISK"
                                                : "MONITORING";
                        }
                        history = alertHistory;
                    }
#pragma warning disable CS4014
                    dispatcher.BeginInvoke((Action)(() => AlertHistoryUpdated?.Invoke(history)));
#pragma warning restore CS4014
                    logger.Info($"[VDS] Live alerts updated: total={mapped.Count} critical={criticalAlerts} warning={warningAlerts}");
                }
                } // end items check
            } // end IDLE guard

            // Poll replay status while ML analysis is running.
            var currentMlState = MlAnalysisState;
            if (currentMlState == "ANALYZING" || currentMlState == "QUEUED")
            {
                var replayStatus = await pythonApiClient.GetReplayStatusAsync(CancellationToken.None);
                if (replayStatus != null)
                {
                    if (replayStatus.State == "completed")
                    {
                        lock (sync) { mlAnalysisState = "COMPLETE"; }
                        var replayAlerts = await pythonApiClient.GetReplayAlertsAsync(CancellationToken.None);
                        if (replayAlerts?.Items is { Count: > 0 } replayItems)
                        {
                            ApplyReplayAlerts(replayItems);
                        }
                    }
                    else if (replayStatus.State == "running")
                    {
                        // Partial update every 10 ticks (~5 s) during analysis
                        if (signalPollCounter % 10 == 0)
                        {
                            var partial = await pythonApiClient.GetPartialReplayAlertsAsync(CancellationToken.None);
                            if (partial?.Items is { Count: > 0 } partialItems)
                                ApplyReplayAlerts(partialItems);
                        }
                    }
                    else if (replayStatus.State == "error" || replayStatus.State == "failed")
                    {
                        lock (sync) { mlAnalysisState = "ERROR"; }
                        logger.Error($"[VDS] Replay analysis failed: {replayStatus.Error}");
                        // Still apply whatever partial alerts were collected before the crash
                        var partial = await pythonApiClient.GetPartialReplayAlertsAsync(CancellationToken.None);
                        if (partial?.Items is { Count: > 0 } partialItems)
                            ApplyReplayAlerts(partialItems);
                    }
                }
            }

            // Poll live signals every 5 ticks (2.5 s) — drives the CAN frame monitor.
            signalPollCounter++;
            if (signalPollCounter % 5 == 0)
            {
                var sigResp = await pythonApiClient.GetLiveSignalsAsync(30, CancellationToken.None);
                if (sigResp?.Items is { Count: > 0 } sigItems)
                {
                    var snapshot = (IReadOnlyList<LiveSignalItem>)sigItems.AsReadOnly();
#pragma warning disable CS4014
                    dispatcher.BeginInvoke((Action)(() => LiveFramesUpdated?.Invoke(snapshot)));
#pragma warning restore CS4014
                }

                // Poll aggregated decoded engineering values — populates LIVE SIGNAL MONITOR.
                var decResp = await pythonApiClient.GetLiveDecodedSignalsAsync(CancellationToken.None);
                if (decResp?.Items is { Count: > 0 } decItems)
                {
                    var now = DateTime.UtcNow;
                    var decoded = decItems
                        .Select(d => new DecodedSignal
                        {
                            Name         = d.Name,
                            Value        = d.Value,
                            Unit         = d.Unit,
                            FeatureKey   = d.System,
                            CanId        = TryParseCanId(d.CanId),
                            TimestampUtc = now,
                            OutOfRange   = d.OutOfRange,
                        })
                        .ToList();
                    lock (sync) { currentSignals = decoded; }
#pragma warning disable CS4014
                    dispatcher.BeginInvoke((Action)(() => SignalsUpdated?.Invoke(decoded)));
#pragma warning restore CS4014
                }
            }
        }
        catch (Exception ex)
        {
            logger.Error("[VDS] Refresh tick failed.", ex);
        }
        finally
        {
            isRefreshing = false;
        }
    }

    private void ApplyReplayAlerts(IList<LiveAlertItem> items)
    {
        var mapped = items
            .Select(a => new RuntimeAlertEvent
            {
                RelativeSeconds = a.Timestamp,
                TimestampUtc    = DateTime.UtcNow.Date.AddSeconds(a.Timestamp),
                CanId           = a.CanId,
                Severity        = a.Severity,
                Score           = a.Score,
                AttackType      = string.IsNullOrWhiteSpace(a.DominantDetectionLayer) ? "REPLAY" : a.DominantDetectionLayer.ToUpperInvariant(),
                Reason          = a.Reason,
            })
            .OrderBy(a => a.RelativeSeconds)
            .ToList();
        IReadOnlyList<RuntimeAlertEvent> history;
        lock (sync)
        {
            alertHistory   = mapped;
            totalAlerts    = mapped.Count;
            criticalAlerts = mapped.Count(a => a.Severity == "CRITICAL");
            warningAlerts  = mapped.Count(a => a.Severity == "HIGH" || a.Severity == "WARNING");
            if (mapped.Count > 0)
            {
                topSuspiciousCanId  = mapped.OrderByDescending(a => a.Score).First().CanId;
                detectionConfidence = Math.Min(100.0, mapped.Max(a => a.Score) * 100.0);
                detectedAttackType  = criticalAlerts > 0 ? "INTRUSION DETECTED"
                                    : warningAlerts  > 0 ? "ELEVATED RISK"
                                    : "MONITORING";
            }
            history = alertHistory;
        }
        dispatcher.BeginInvoke(() => AlertHistoryUpdated?.Invoke(history));
        logger.Info($"[VDS] Replay alerts applied: total={mapped.Count} critical={criticalAlerts}");
    }

    private static int TryParseCanId(string raw)
    {
        var s = raw.Trim();
        if (s.StartsWith("0x", StringComparison.OrdinalIgnoreCase) || s.StartsWith("0X", StringComparison.OrdinalIgnoreCase))
        {
            if (int.TryParse(s.Substring(2), System.Globalization.NumberStyles.HexNumber, null, out var hex))
                return hex;
        }
        return int.TryParse(s, out var dec) ? dec : 0;
    }
}
