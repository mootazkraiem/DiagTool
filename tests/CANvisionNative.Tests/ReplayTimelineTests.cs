using System.Globalization;
using System.IO;
using CANvision.Native.Services;
using CANvision.Native.ViewModels;
using Xunit;

namespace CANvision.Native.Tests;

/// <summary>
/// The Log Playback timeline places everything by capture timestamp over the
/// session's real duration. These pin that mapping down, and check it against a
/// real replay read independently from the raw file.
/// </summary>
public sealed class ReplayTimelineTests
{
    private const double Width = 920; // the timeline canvas width used by the view

    [Fact]
    public void Session_start_maps_to_the_left_edge_and_end_to_the_right_edge()
    {
        Assert.Equal(0, ReplayTimeline.ToX(0.0, 0.0, 33.570498, Width));
        Assert.Equal(Width, ReplayTimeline.ToX(33.570498, 0.0, 33.570498, Width));
    }

    [Fact]
    public void A_timestamp_lands_at_its_proportional_position()
    {
        // Halfway through the real fuzzy replay capture.
        Assert.Equal(Width / 2, ReplayTimeline.ToX(16.785249, 0.0, 33.570498, Width), 6);
        // A session that does not start at zero is measured from its own start.
        Assert.Equal(Width / 4, ReplayTimeline.ToX(12.5, 10.0, 20.0, Width), 6);
    }

    [Fact]
    public void Position_follows_time_not_frame_index()
    {
        // Three frames at t = 0, 0, 10: the middle frame is half-way by index but at
        // time zero. Index-based placement drew it mid-track.
        double[] timestamps = { 0.0, 0.0, 10.0 };
        Assert.Equal(0, ReplayTimeline.ToX(timestamps[1], timestamps[0], timestamps[2], Width));
    }

    [Theory]
    [InlineData(-5.0, 0.0)]
    [InlineData(99.0, 1.0)]
    public void Positions_outside_the_session_are_clamped(double t, double expected)
        => Assert.Equal(expected, ReplayTimeline.Fraction(t, 0.0, 10.0));

    [Fact]
    public void A_zero_length_session_maps_everything_to_the_left_edge()
        => Assert.Equal(0, ReplayTimeline.Fraction(5.0, 5.0, 5.0));

    [Theory]
    [InlineData(33.570498, 33.570498, "00:33")]
    [InlineData(0.0, 33.570498, "00:00")]
    [InlineData(4893.0, 4893.0, "1:21:33")]   // must not drop the hour ("21:33")
    [InlineData(1223.25, 4893.0, "0:20:23")]  // an hour-long axis keeps one format
    public void Axis_labels_format_offsets_from_session_start(double seconds, double span, string expected)
        => Assert.Equal(expected, ReplayTimeline.FormatOffset(seconds, span));

    [Theory]
    [InlineData(33.568392, "00:00:33")]
    [InlineData(4893.0, "01:21:33")]
    public void Duration_readout_is_the_capture_span(double span, string expected)
        => Assert.Equal(expected, ReplayTimeline.FormatDuration(span));

    // ── against a real replay ────────────────────────────────────────────────

    [Fact]
    public async Task Real_replay_duration_is_the_capture_span_not_the_delay_sum()
    {
        var path = Path.Combine(FindRepoRoot(), "assets", "Validation", "validation_fuzzy_replay.csv");

        // Expected span read straight from the raw file, independent of the importer.
        var rows = File.ReadAllLines(path).Where(line => line.Trim().Length > 0).ToArray();
        static double Ts(string line) => double.Parse(line.Split(',')[0], CultureInfo.InvariantCulture);
        var rawSpan = Ts(rows[rows.Length - 1]) - Ts(rows[0]);

        var logger = new AppLogger();
        var result = await new CanLogImportService(logger, new PythonApiClient(logger))
            .ParseFileAsync(path, skipMlScoring: true);
        var packets = result.Packets.ToList();
        var start = packets[0].Frame.RelativeTimestampSeconds;
        var end = packets[packets.Count - 1].Frame.RelativeTimestampSeconds;

        Assert.Equal(rawSpan, end - start, 3);
        Assert.Equal("00:00:33", ReplayTimeline.FormatDuration(end - start));
        Assert.Equal("00:33", ReplayTimeline.FormatOffset(end - start, end - start));

        // What the old readout showed: replay delays floored at 1 ms summed to ~49.9 s
        // for this 33.6 s capture, because most frames share a timestamp.
        var delaySum = packets.Sum(p => p.DelayMilliseconds) / 1000.0;
        Assert.True(delaySum > rawSpan + 10, $"delay sum {delaySum:F1} s vs capture span {rawSpan:F1} s");
    }

    private static string FindRepoRoot()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null && !File.Exists(Path.Combine(dir.FullName, "CANvisionNative.csproj")))
        {
            dir = dir.Parent;
        }
        return dir?.FullName ?? throw new DirectoryNotFoundException("repository root not found");
    }
}
