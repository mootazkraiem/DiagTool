using System;

namespace CANvision.Native.ViewModels;

/// <summary>
/// The single time-to-position mapping for the Log Playback timeline.
///
/// Every element on the timeline - axis labels, playback cursor, detection /
/// alert / ground-truth marks, attack windows - is placed by its capture
/// timestamp relative to the session start, over the session's real duration.
///
/// Two earlier shortcuts made the timeline disagree with itself:
/// <list type="bullet">
/// <item>Positions came from frame INDEX (index / count). CAN captures are not
/// uniform in time - bursts put thousands of frames in a few milliseconds - so
/// "half the frames" is not "half the time".</item>
/// <item>The duration readout summed the per-packet replay delays, which are
/// floored at 1 ms. Frames that share a timestamp each added a phantom
/// millisecond: validation_fuzzy_replay.csv spans 33.6 s of capture but its
/// delays summed to 49.9 s.</item>
/// </list>
/// </summary>
internal static class ReplayTimeline
{
    /// <summary>Position of <paramref name="t"/> in [start, end] as 0-1, clamped.</summary>
    public static double Fraction(double t, double start, double end)
    {
        var span = end - start;
        if (span <= 0 || double.IsNaN(t)) return 0;
        return Math.Max(0, Math.Min(1, (t - start) / span));
    }

    /// <summary>Horizontal position of <paramref name="t"/> on a track <paramref name="width"/> wide.</summary>
    public static double ToX(double t, double start, double end, double width)
        => Fraction(t, start, end) * width;

    /// <summary>
    /// An offset from session start for axis labels. Switches to h:mm:ss once the
    /// session reaches an hour, so the hour is never silently dropped
    /// (1:21:28 used to print as "21:28").
    /// </summary>
    public static string FormatOffset(double seconds, double spanSeconds)
    {
        var value = TimeSpan.FromSeconds(Math.Max(0, seconds));
        return spanSeconds >= 3600 ? value.ToString(@"h\:mm\:ss") : value.ToString(@"mm\:ss");
    }

    /// <summary>The session duration readout (hh:mm:ss) for a capture span in seconds.</summary>
    public static string FormatDuration(double spanSeconds)
        => TimeSpan.FromSeconds(Math.Max(0, spanSeconds)).ToString(@"hh\:mm\:ss");
}
