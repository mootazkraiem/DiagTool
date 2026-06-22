using System.Collections.Generic;

namespace CANvision.Native.Models;

public sealed class SectionDescriptor
{
    public SectionDescriptor(
        SectionKey key,
        string moduleCode,
        string title,
        string menuDescription,
        string briefingDescription)
    {
        Key = key;
        ModuleCode = moduleCode;
        Title = title;
        MenuDescription = menuDescription;
        BriefingDescription = briefingDescription;
    }

    public SectionKey Key { get; }

    public string ModuleCode { get; }

    public string Title { get; }

    public string MenuDescription { get; }

    public string BriefingDescription { get; }
}

public static class SectionCatalog
{
    private static readonly IReadOnlyDictionary<SectionKey, SectionDescriptor> Descriptors =
        new Dictionary<SectionKey, SectionDescriptor>
        {
            [SectionKey.Dashboard] = new(
                SectionKey.Dashboard,
                "01",
                "Dashboard",
                "Live readiness, sync state, and launch-critical vehicle status.",
                "Monitor live vehicle snapshot, system readiness, and current operational state."),
            [SectionKey.Telemetry] = new(
                SectionKey.Telemetry,
                "02",
                "Telemetry",
                "Battery, thermal, speed, voltage, and CAN-backed live signal streams.",
                "Inspect battery, temperature, speed, and all decoded CAN signals in real time."),
            [SectionKey.Diagnostics] = new(
                SectionKey.Diagnostics,
                "03",
                "Diagnostics",
                "Subsystem scans, warnings, and deployment-critical fault inspection.",
                "Run full system scans, review DTCs, and detect anomalies with AI analysis."),
            [SectionKey.LogPlayback] = new(
                SectionKey.LogPlayback,
                "04",
                "Log Playback",
                "Historical replay, recorded session review, and timeline inspection.",
                "Import and replay recorded CAN sessions with timeline and event controls."),
            [SectionKey.Settings] = new(
                SectionKey.Settings,
                "06",
                "Settings",
                "Data sources, interface behavior, and calibration controls.",
                "Configure OBD2 adapter, vehicle profiles, AI model, and export preferences."),
            [SectionKey.Home] = new(
                SectionKey.Home,
                "00",
                "Home",
                "Garage command deck and system overview.",
                "Main hub for system status, vehicle selection, and navigation."),
            [SectionKey.AnomalyIntel] = new(
                SectionKey.AnomalyIntel,
                "08",
                "Anomaly Intel",
                "AI-powered anomaly explanation and LLM threat analysis.",
                "Review detected anomalies with Gemini/Ollama/RAG explanations, layer attribution, and mitigation guidance."),
        };


    public static IReadOnlyList<SectionDescriptor> All =>
        new List<SectionDescriptor>(Descriptors.Values);

    public static SectionDescriptor? For(SectionKey key)
        => Descriptors.TryGetValue(key, out var d) ? d : null;
}
