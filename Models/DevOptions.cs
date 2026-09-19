namespace CANvision.Native.Models;

/// <summary>
/// Development-only launch switches, set from command-line arguments in
/// <c>App.OnStartup</c>. With no arguments every flag stays false and the
/// application behaves exactly as it does in production.
///
/// Exists so UI work on a single screen does not require re-importing a CAN
/// log on every launch. Pass <c>--dashboard</c> to boot straight into the
/// Dashboard with the "no data yet" scrim suppressed.
/// </summary>
public static class DevOptions
{
    /// <summary>Boot directly into a section instead of the Home screen.</summary>
    public static SectionKey? StartupSection { get; set; }

    /// <summary>
    /// Suppress the empty-state overlay that normally covers every section
    /// until a log has been analysed. Layout work only — it hides the scrim,
    /// it does not fabricate any data.
    /// </summary>
    public static bool SkipDataGate { get; set; }
}
