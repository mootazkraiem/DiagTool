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

// ──────────────────────────────────────────────────────────────────────────────
// AnomalyIntelViewModel — AI alert list + grounded chatbot interface
// ──────────────────────────────────────────────────────────────────────────────

public sealed class AnomalyIntelViewModel : SectionViewModel
{
    private readonly PythonApiClient pythonApiClient;
    private string engineStatusText = "CHECKING...";
    private string engineDetailText = "CONTACTING BACKEND";
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
        _ = RefreshEngineStatusAsync();
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

    // Real analyst-engine state from the backend's health endpoint (the same source
    // Settings shows), instead of an always-"ACTIVE" label.
    public string EngineStatusText { get => engineStatusText; private set => SetProperty(ref engineStatusText, value); }
    public string EngineDetailText { get => engineDetailText; private set => SetProperty(ref engineDetailText, value); }

    private async Task RefreshEngineStatusAsync()
    {
        // The backend may still be starting when this view model is built.
        for (var attempt = 0; attempt < 15; attempt++)
        {
            if (attempt > 0)
                await Task.Delay(2000).ConfigureAwait(true);
            try
            {
                var health = await pythonApiClient.GetSystemHealthDetailAsync(System.Threading.CancellationToken.None).ConfigureAwait(true);
                if (health is null)
                {
                    EngineStatusText = "OFFLINE";
                    EngineDetailText = "BACKEND UNREACHABLE";
                    continue;
                }

                var provider = string.IsNullOrWhiteSpace(health.LlmProvider) ? "NONE" : health.LlmProvider.ToUpperInvariant();
                EngineStatusText = health.ModelLoaded ? "ONLINE" : "MODEL NOT LOADED";
                EngineDetailText = $"LLM {provider}";
                return;
            }
            catch
            {
                EngineStatusText = "OFFLINE";
                EngineDetailText = "BACKEND UNREACHABLE";
            }
        }
    }

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

    /// <summary>The alert "SELECT FIRST" acts on. Binding a command parameter to Alerts[0]
    /// throws inside WPF whenever the list is empty, so the view binds this instead.</summary>
    public AlertDetailItem? FirstAlert => Alerts.Count > 0 ? Alerts[0] : null;
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
            OnPropertyChanged(nameof(FirstAlert));
            OnPropertyChanged(nameof(HasAlerts));
            OnPropertyChanged(nameof(AlertCountText));
            OnPropertyChanged(nameof(CriticalCount));
            OnPropertyChanged(nameof(HighCount));
            return;
        }

        for (var i = 0; i < history.Count; i++)
            Alerts.Add(BuildDetailItem(i, history[i]));

        StatusText = $"SHOWING {Alerts.Count} IDS ALERT{(Alerts.Count == 1 ? "" : "S")}";
        OnPropertyChanged(nameof(FirstAlert));
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
        // Attack classes named by the backend knowledge base (offline analysis).
        if (s.Contains("DOS") || s.Contains("FLOOD"))                       return "DOS / FLOOD";
        if (s.Contains("FUZZ"))                                             return "FUZZY";
        if (s.Contains("SPOOF") || s.Contains("IMPERSONATION"))             return "SPOOFING";
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
