using System.Collections.Generic;
using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;

namespace CANvision.Native.Models;

public sealed class AlertDetailItem : ObservableObject
{
    private string explanationSummary = string.Empty;
    private string explanationDetail = string.Empty;
    private string explanationRecommendation = string.Empty;
    private string kbMatchLabel = string.Empty;
    private bool isLoading;
    private bool hasExplanation;
    private string explanationMode = "rule_based";

    public int    Index         { get; set; }
    public string Time          { get; set; } = string.Empty;
    public string CanId         { get; set; } = "0x000";
    public string Severity      { get; set; } = "LOW";
    public string SeverityColor { get; set; } = "#56F0AC";
    public double Score         { get; set; }
    public string ScoreText     => $"{Score:F3}";
    public string AttackType    { get; set; } = "UNKNOWN";
    public string Reason        { get; set; } = string.Empty;

    public double LayerTiming   { get; set; }
    public double LayerPayload  { get; set; }
    public double LayerMl       { get; set; }
    public double LayerTemporal { get; set; }

    // Multi-layer detection enrichment
    public bool   PlausibilityPassed    { get; set; } = true;
    public string PlausibilityText      { get; set; } = string.Empty;
    public bool   TimingAnomaly         { get; set; }
    public double TimingScore           { get; set; }
    public string TemporalPattern       { get; set; } = "normal";
    public double TemporalScore         { get; set; }
    public string DetectionLayersText   { get; set; } = "ML";
    public string RecommendedResponse   { get; set; } = string.Empty;

    public bool HasPlausibilityViolation => !PlausibilityPassed && !string.IsNullOrEmpty(PlausibilityText);
    public bool HasTimingAnomaly         => TimingAnomaly && TimingScore > 0;
    public bool HasTemporalAnomaly       => TemporalPattern != "normal";
    public bool HasRecommendedResponse   => !string.IsNullOrEmpty(RecommendedResponse);

    public ObservableCollection<DecodedSignalItem> DecodedSignals { get; } = new();
    public bool HasDecodedSignals => DecodedSignals.Count > 0;
    public string DecodedSystemName => DecodedSignals.Count > 0 ? DecodedSignals[0].System : string.Empty;

    public void SetDecodedSignals(IEnumerable<DecodedSignalItem> items)
    {
        DecodedSignals.Clear();
        foreach (var s in items)
            DecodedSignals.Add(s);
        OnPropertyChanged(nameof(HasDecodedSignals));
        OnPropertyChanged(nameof(DecodedSystemName));
    }

    public string ExplanationSummary
    {
        get => explanationSummary;
        set => SetProperty(ref explanationSummary, value);
    }

    public string ExplanationDetail
    {
        get => explanationDetail;
        set => SetProperty(ref explanationDetail, value);
    }

    public string ExplanationRecommendation
    {
        get => explanationRecommendation;
        set => SetProperty(ref explanationRecommendation, value);
    }

    public bool IsLoading
    {
        get => isLoading;
        set
        {
            SetProperty(ref isLoading, value);
            OnPropertyChanged(nameof(CanExplain));
        }
    }

    public bool HasExplanation
    {
        get => hasExplanation;
        set
        {
            SetProperty(ref hasExplanation, value);
            OnPropertyChanged(nameof(CanExplain));
        }
    }

    public string KbMatchLabel
    {
        get => kbMatchLabel;
        set
        {
            SetProperty(ref kbMatchLabel, value);
            OnPropertyChanged(nameof(HasKbMatch));
        }
    }

    public bool HasKbMatch => !string.IsNullOrEmpty(kbMatchLabel);

    public bool CanExplain => !HasExplanation && !IsLoading;

    /// <summary>Raw engine identifier from the backend: "gemini" | "ollama" | "rule_based".</summary>
    public string ExplanationMode
    {
        get => explanationMode;
        set
        {
            SetProperty(ref explanationMode, value);
            OnPropertyChanged(nameof(ExplanationModeLabel));
            OnPropertyChanged(nameof(IsGenerativeAi));
        }
    }

    /// <summary>Honest, user-facing label — never claims AI when the backend used the rule-based fallback.</summary>
    public string ExplanationModeLabel => explanationMode switch
    {
        "gemini"  => "GEMINI AI",
        "ollama"  => "LOCAL AI (OLLAMA)",
        _         => "RULE-BASED (NO LLM CONFIGURED)",
    };

    public bool IsGenerativeAi => explanationMode is "gemini" or "ollama";

    public IAsyncRelayCommand? ExplainCommand { get; set; }
}

public sealed class ChatMessage : ObservableObject
{
    private string text = string.Empty;

    public string Role { get; set; } = "user"; // "user" | "ai"
    public string Time { get; set; } = string.Empty;
    public bool IsUser => Role == "user";
    public bool IsAi   => Role == "ai";

    public string Text
    {
        get => text;
        set => SetProperty(ref text, value);
    }

    /// <summary>"gemini" | "ollama" | "rule_based" — only meaningful when Role == "ai".</summary>
    public string Mode { get; set; } = "rule_based";

    public string ModeLabel => Mode switch
    {
        "gemini" => "GEMINI AI",
        "ollama" => "LOCAL AI (OLLAMA)",
        _        => "RULE-BASED",
    };
}

public sealed class TimelineMarker
{
    public double X             { get; set; }  // Canvas.Left (0–1000 px)
    public string Color         { get; set; } = "#00C8C8";
    public string CanId         { get; set; } = "0x000";
    public string Severity      { get; set; } = "WARNING";
    public double RelativePos   { get; set; }  // 0.0–1.0
    public AlertDetailItem? Alert { get; set; }
}

public sealed class LiveFrameRow
{
    public string Time     { get; set; } = string.Empty;
    public string CanId    { get; set; } = "0x000";
    public string Bytes    { get; set; } = "00 00 00 00 00 00 00 00";
    public string Score    { get; set; } = "0.00";
    public string Severity { get; set; } = "LOW";
    public string SeverityColor { get; set; } = "#56F0AC";
}

public sealed class RuntimeAlertEvent
{
    public DateTime TimestampUtc { get; set; } = DateTime.UtcNow;
    public double RelativeSeconds { get; set; }   // raw CAN timestamp (seconds), used for packet matching
    public string CanId { get; set; } = "0x000";
    public string Severity { get; set; } = "INFO";
    public double Score { get; set; }
    public string AttackType { get; set; } = "UNKNOWN";
    public string Reason { get; set; } = string.Empty;
}
