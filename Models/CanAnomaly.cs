namespace CANvision.Native.Models;

public sealed class CanAnomaly
{
    public string Code { get; set; } = string.Empty;
    public string Title { get; set; } = string.Empty;
    public string Description { get; set; } = string.Empty;
    public string Severity { get; set; } = "WARNING"; // Legacy string category
    public double SeverityScore { get; set; } // 0-100 numeric score
    public double AnomalyScore { get; set; } // Raw ML score
    public int RelatedCanId { get; set; }
    public DateTime TimestampUtc { get; set; } = DateTime.UtcNow;
    public string Source { get; set; } = "runtime";
}

