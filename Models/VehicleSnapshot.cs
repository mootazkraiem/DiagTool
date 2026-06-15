using Newtonsoft.Json;

namespace CANvision.Native.Models;

public sealed class VehicleSnapshot
{
    [JsonProperty("battery")]
    public int Battery { get; set; }

    [JsonProperty("temperature")]
    public int Temperature { get; set; }

    [JsonProperty("motor_status")]
    public string MotorStatus { get; set; } = "UNKNOWN";

    [JsonProperty("source")]
    public string Source { get; set; } = "offline";

    [JsonProperty("updated_at")]
    public DateTime UpdatedAt { get; set; } = DateTime.UtcNow;

    // Detailed Telemetry
    [JsonProperty("SOC")]
    public double SOC { get; set; }

    [JsonProperty("SOH")]
    public double SOH { get; set; }

    [JsonProperty("BatteryVoltage")]
    public double BatteryVoltage { get; set; }

    [JsonProperty("BatteryCurrent")]
    public double BatteryCurrent { get; set; }

    [JsonProperty("BatteryPower")]
    public double BatteryPower { get; set; }

    [JsonProperty("BatteryTemp")]
    public double BatteryTemp { get; set; }

    [JsonProperty("VehicleSpeed")]
    public double VehicleSpeed { get; set; }

    [JsonProperty("MotorTemp")]
    public double MotorTemp { get; set; }

    [JsonProperty("MotorRPM")]
    public int MotorRPM { get; set; }

    [JsonProperty("InverterTemp")]
    public double InverterTemp { get; set; }

    [JsonProperty("DriveMode")]
    public string DriveMode { get; set; } = "NORMAL";

    [JsonProperty("Gear")]
    public string Gear { get; set; } = "P";

    // Faults
    [JsonProperty("OverheatFault")]
    public bool OverheatFault { get; set; }

    [JsonProperty("OverCurrentFault")]
    public bool OverCurrentFault { get; set; }

    [JsonProperty("UnderVoltageFault")]
    public bool UnderVoltageFault { get; set; }

    [JsonProperty("BMSFault")]
    public bool BMSFault { get; set; }

    [JsonProperty("MotorFault")]
    public bool MotorFault { get; set; }

    [JsonProperty("PerformanceScore")]
    public double PerformanceScore { get; set; }

    [JsonProperty("Frequency")]
    public double Frequency { get; set; }

    [JsonProperty("TimeDiff")]
    public double TimeDiff { get; set; }

    [JsonProperty("PeakAmperage")]
    public double PeakAmperage { get; set; }

    [JsonProperty("anomaly_score")]
    public double AnomalyScore { get; set; }

    [JsonProperty("live_fps")]
    public double LiveFps { get; set; }

    [JsonProperty("live_can_id")]
    public int LiveCanId { get; set; }

    public static VehicleSnapshot Default() =>
        new()
        {
            Battery = 92,
            Temperature = 41,
            MotorStatus = "OK",
            Source = "bootstrap",
            UpdatedAt = DateTime.UtcNow,
            SOC = 92.0,
            BatteryTemp = 41.0,
            VehicleSpeed = 0.0,
            MotorTemp = 45.0,
        };
}
