namespace CANvision.Native.Models;

public sealed class CanFrame
{
    public DateTime TimestampUtc { get; set; }
    public double RelativeTimestampSeconds { get; set; }
    public int CanId { get; set; }
    public byte[] Data { get; set; } = new byte[8];
}

public sealed class SignalDefinition
{
    public string Name { get; set; } = string.Empty;
    public int StartBit { get; set; }
    public int Length { get; set; }
    public bool IsLittleEndian { get; set; } = true;
    public bool IsSigned { get; set; }
    public double Factor { get; set; } = 1.0;
    public double Offset { get; set; }
    public string Unit { get; set; } = string.Empty;
    public string FeatureKey { get; set; } = string.Empty;
}

public sealed class DecodedSignal
{
    public string Name { get; set; } = string.Empty;
    public double Value { get; set; }
    public string Unit { get; set; } = string.Empty;
    public DateTime TimestampUtc { get; set; }
    public int CanId { get; set; }
    public string FeatureKey { get; set; } = string.Empty;
}

public sealed class DiagnosticFault
{
    public string Code { get; set; } = string.Empty;
    public string Description { get; set; } = string.Empty;
    public string Severity { get; set; } = "INFO";
    public double SeverityScore { get; set; }
    public string Source { get; set; } = "signal";
    public DateTime TimestampUtc { get; set; }
    public int RelatedCanId { get; set; }
}

public sealed class PlaybackPacket
{
    public CanFrame Frame { get; set; } = new();
    public IReadOnlyList<DecodedSignal> Signals { get; set; } = Array.Empty<DecodedSignal>();
    public VehicleSnapshot Snapshot { get; set; } = VehicleSnapshot.Default();
    public IReadOnlyList<CanAnomaly> Anomalies { get; set; } = Array.Empty<CanAnomaly>();
    public string EventText { get; set; } = string.Empty;
    public int DelayMilliseconds { get; set; }
}
