using CANvision.Native.Models;

namespace CANvision.Native.Services;

public static class PredefinedCanSchema
{
    public static readonly Dictionary<int, List<SignalDefinition>> DbcMap = new()
    {
        [0x100] =
        [
            new SignalDefinition { Name = "Battery_SOC", FeatureKey = "Battery_SOC", StartBit = 0, Length = 8, Factor = 0.4, Unit = "%" },
            new SignalDefinition { Name = "Battery_SOH", FeatureKey = "Battery_SOH", StartBit = 8, Length = 8, Factor = 0.4, Unit = "%" },
        ],
        [0x101] =
        [
            new SignalDefinition { Name = "Battery_Voltage", FeatureKey = "Voltage", StartBit = 0, Length = 16, Factor = 0.1, Unit = "V" },
            new SignalDefinition { Name = "Battery_Current", FeatureKey = "Current", StartBit = 16, Length = 16, Factor = 0.1, Offset = -3200, IsSigned = true, Unit = "A" },
        ],
        [0x102] =
        [
            new SignalDefinition { Name = "Battery_Temp", FeatureKey = "Temp", StartBit = 0, Length = 8, Factor = 1.0, Offset = -40, Unit = "C" },
            new SignalDefinition { Name = "Peak_Amperage", FeatureKey = "PeakAmperage", StartBit = 8, Length = 8, Factor = 4.0, Unit = "A" },
        ],
        [0x103] =
        [
            new SignalDefinition { Name = "Vehicle_Speed", FeatureKey = "Speed", StartBit = 0, Length = 16, Factor = 0.1, Unit = "km/h" },
            new SignalDefinition { Name = "Motor_RPM", FeatureKey = "RPM", StartBit = 16, Length = 16, Factor = 1.0, Unit = "rpm" },
        ],
        [0x104] =
        [
            new SignalDefinition { Name = "Motor_Temp", FeatureKey = "MotorTemp", StartBit = 0, Length = 8, Factor = 1.0, Offset = -40, Unit = "C" },
            new SignalDefinition { Name = "Inverter_Temp", FeatureKey = "InverterTemp", StartBit = 8, Length = 8, Factor = 1.0, Offset = -40, Unit = "C" },
        ],
        [0x105] =
        [
            new SignalDefinition { Name = "FaultFlags", FeatureKey = "FaultFlags", StartBit = 0, Length = 8, Factor = 1.0, Unit = "bits" },
        ],
    };

    public static readonly Dictionary<int, string> TranslationMap = new()
    {
        [0x100] = "BMS_STATUS",
        [0x101] = "BMS_POWER",
        [0x102] = "BMS_THERMAL",
        [0x103] = "DRIVE_STATUS",
        [0x104] = "INVERTER_STATUS",
        [0x105] = "FAULT_STATUS",
    };

    public static readonly string[] FeatureVectorOrder =
    [
        "Battery_SOC",
        "Voltage",
        "Temp",
        "Current",
        "RPM",
        "Speed",
        "MotorTemp",
        "InverterTemp",
        "PeakAmperage",
    ];
}
