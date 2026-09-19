using System.IO;
using CANvision.Native.Services;
using Xunit;

namespace CANvision.Native.Tests;

/// <summary>
/// The Log Playback Ground Truth lane reads the validation replays' _gt.csv label
/// files. Expected spans were computed independently from the raw files (Python):
/// each file has one contiguous labelled attack period and no normal rows inside it.
/// </summary>
public sealed class GroundTruthLabelsTests
{
    private static readonly string Validation = Path.Combine(FindRepoRoot(), "assets", "Validation");

    [Theory]
    [InlineData("dos", 0.79571, 22.994454, "DoS_attack")]
    [InlineData("fuzzy", 0.871255, 33.570498, "Fuzzy_attack")]
    [InlineData("gear", 1.21164, 15.397584, "Gear_attack")]
    [InlineData("rpm", 0.921618, 14.917851, "RPM_attack")]
    public void Validation_label_files_give_their_single_attack_span(string name, double start, double end, string label)
    {
        var spans = GroundTruthLabels.ReadSpans(Path.Combine(Validation, $"validation_{name}_gt.csv"));

        var span = Assert.Single(spans);
        Assert.Equal(start, span.Start, 6);
        Assert.Equal(end, span.End, 6);
        Assert.Equal(label, span.Label);
    }

    [Fact]
    public void A_replay_log_finds_its_label_file_and_other_logs_find_none()
    {
        Assert.Equal(Path.Combine(Validation, "validation_dos_gt.csv"),
            GroundTruthLabels.FindFor(Path.Combine(Validation, "validation_dos_replay.csv")));
        Assert.Null(GroundTruthLabels.FindFor(Path.Combine(FindRepoRoot(), "assets", "Skoda Enyaq", "file_13.csv")));
        Assert.Null(GroundTruthLabels.FindFor(null));
    }

    [Fact]
    public void Labels_split_into_spans_at_normal_rows_and_label_changes()
    {
        var path = Path.GetTempFileName();
        try
        {
            File.WriteAllLines(path, new[]
            {
                "timestamp,attack_type",
                "0.0,normal", "1.0,DoS", "2.0,DoS", "3.0,normal", "4.0,DoS", "5.0,Fuzzy", "6.0,Fuzzy",
            });
            var spans = GroundTruthLabels.ReadSpans(path);

            Assert.Equal(new[] { (1.0, 2.0, "DoS"), (4.0, 4.0, "DoS"), (5.0, 6.0, "Fuzzy") },
                spans.Select(s => (s.Start, s.End, s.Label)));
        }
        finally
        {
            File.Delete(path);
        }
    }

    private static string FindRepoRoot()
    {
        var dir = new DirectoryInfo(AppDomain.CurrentDomain.BaseDirectory);
        while (dir is not null && !File.Exists(Path.Combine(dir.FullName, "CANvisionNative.csproj")))
        {
            dir = dir.Parent;
        }

        return dir?.FullName ?? throw new InvalidOperationException("Repository root not found.");
    }
}
