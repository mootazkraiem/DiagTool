namespace CANvision.Native.Models;

/// <summary>
/// Global analysis lifecycle state. Drives navigation unlocking and empty-state display.
/// </summary>
public enum AppState
{
    /// <summary>No dataset has been imported.</summary>
    NoDataset,

    /// <summary>A dataset has been parsed and is ready for analysis.</summary>
    DatasetLoaded,

    /// <summary>ML analysis pipeline is currently running.</summary>
    Analyzing,

    /// <summary>Analysis complete — all screens unlocked.</summary>
    AnalysisComplete,

    /// <summary>Live hardware or mock session is active — all screens unlocked.</summary>
    LiveSession,
}
