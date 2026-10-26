using System.Linq;
using CANvision.Native.Models;
using CANvision.Native.ViewModels;
using Xunit;

namespace CANvision.Native.Tests;

/// <summary>
/// The Dashboard dataset card: its numbers are the backend's measured facts, its role
/// sentence follows the model corpus, and unlabelled data is never called an attack.
/// </summary>
public sealed class DatasetCardTests
{
    private static DatasetFactsResponse Jaguar(string role) => new()
    {
        FileName = "canbus_turningon_quickly.csv", Folder = "Jaguar IPACE", ModelId = "jaguar_ipace",
        Vehicle = "Jaguar I-PACE", Frames = 50361, DurationS = 16.63, CanIds = 146, RateHz = 3028.2,
        Role = role, ModelVersion = "clean-2-002", TrainingRecordings = 3, TrainingFrames = 233598, HoldoutRecordings = 1,
    };

    [Fact]
    public void Holdout_SaysTheModelNeverSawIt_WithMeasuredNumbers()
    {
        var text = string.Join(" ", DatasetCard.Paragraphs(Jaguar("holdout"), hasLabels: false));
        Assert.Contains("50,361 messages recorded over 16.6 seconds", text);
        Assert.Contains("about 3,028 messages per second", text);
        Assert.Contains("146 different message types", text);
        Assert.Contains("never saw this recording", text);
        Assert.Contains("3 recordings (233,598 messages)", text);
        Assert.Equal("Jaguar I-PACE · canbus_turningon_quickly.csv", DatasetCard.Title(Jaguar("holdout")));
    }

    [Fact]
    public void Unlabelled_FlagsAreNotConfirmedAttacks()
    {
        var last = DatasetCard.Paragraphs(Jaguar("holdout"), hasLabels: false).Last();
        Assert.Contains("no answer key", last);
        Assert.Contains("not \"this is a confirmed attack\"", last);
    }

    [Fact]
    public void TrainingAndUnknownRoles_AreStatedAsSuch()
    {
        Assert.Contains("one of the 3 recordings", DatasetCard.Paragraphs(Jaguar("training"), false)[1]);
        Assert.Contains("not known", DatasetCard.Paragraphs(Jaguar(""), false)[1]);
        Assert.Equal("Test file (unseen)", DatasetCard.Facts(Jaguar("holdout")).Single(f => f.Label == "ROLE").Value);
    }

    [Theory]
    [InlineData(16.63, "16.6 seconds")]
    [InlineData(2170, "36 min 10 s")]
    [InlineData(7260, "2 h 01 min")]
    public void Duration_IsReadable(double seconds, string expected) => Assert.Equal(expected, DatasetCard.Duration(seconds));
}
