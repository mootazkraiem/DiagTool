using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;

namespace CANvision.Native.Models;

public sealed class AlertDetailItem : ObservableObject
{
    private string explanationSummary = string.Empty;
    private string explanationDetail = string.Empty;
    private string explanationRecommendation = string.Empty;
    private bool isLoading;
    private bool hasExplanation;

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

    public bool CanExplain => !HasExplanation && !IsLoading;

    public IAsyncRelayCommand? ExplainCommand { get; set; }
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
