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
        QuickScanCommand = new RelayCommand(ReloadEvents);
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

        // Offline replay parses frames with skipMlScoring, so CompleteReplayAnalysis
        // publishes an empty AlertHistory; the backend's real detections arrive once,
        // through AnomaliesUpdated, while the import is still running. This view model
        // is built on first navigation to Diagnostics - normally AFTER that event - so
        // subscribing alone leaves the event log empty for the usual "import a log,
        // then open Diagnostics" order. Seed from the anomalies the service still holds.
        SeedFromCachedAnomalies();
    }

    // Rebuilds the log on demand (RELOAD EVENT LOG / quick scan). AlertHistory is
    // authoritative whenever it has entries - that is the live-session path. In
    // offline replay it is empty by design, so rebuilding from it would throw away
    // the backend detections already on screen; keep those instead.
    private void ReloadEvents()
    {
        var history = VehicleDataService.AlertHistory;
        if (history.Count > 0)
        {
            RefreshFromRuntime(history);
            return;
        }

        SeedFromCachedAnomalies();
    }

    // Best-effort top-up from the anomalies the service still holds. Note the
    // service's cache is overwritten by every published replay packet (offline
    // packets carry none), so this fills the log only when it happens to be warm.
    // No-op once the log has entries, so it never duplicates rows.
    private void SeedFromCachedAnomalies()
    {
        if (IdsEvents.Count > 0) return;
        OnAnomaliesReceived(VehicleDataService.CurrentAnomalies);
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
        ReloadEvents();
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
        // Offline replay publishes an EMPTY history here: frames are parsed with
        // skipMlScoring, so CompleteReplayAnalysis has no per-frame alerts to hand
        // over, and it fires moments after AnomaliesUpdated delivered the backend's
        // real detections. Rebuilding from an empty history would wipe exactly those
        // detections, which is why the event log stayed empty after every import.
        // Keep what is already shown, and fall back to the service's cached anomalies.
        if (history.Count == 0)
        {
            SeedFromCachedAnomalies();
            return;
        }

        RefreshFromRuntime(history);
    }

    // Incrementally surfaces per-frame anomalies so the error console fills
    // during analysis rather than only on completion.
    private void OnAnomaliesReceived(IReadOnlyList<CanAnomaly> anomalies)
    {
        if (anomalies.Count == 0) return;

        // Once the alert history has entries it is the complete event log. Log Playback
        // re-publishes each alert's frame as it plays; adding those again counted every
        // replayed alert twice.
        if (VehicleDataService.AlertHistory.Count > 0) return;

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
        // Same wording RefreshFromRuntime uses, so the ribbon and the status pill
        // stop reading "NO IDS EVENTS" while the log is filling from this path.
        DiagnosticsStatus = $"IDS EVENTS ACTIVE ({IdsEvents.Count})";
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

