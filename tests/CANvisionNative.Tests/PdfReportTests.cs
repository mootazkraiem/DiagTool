using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using CANvision.Native.Models;
using CANvision.Native.Services;
using PdfSharp.Pdf.IO;
using Xunit;

namespace CANvision.Native.Tests;

/// <summary>
/// The anomaly report: the reason string is split into readable parts, long reasons
/// wrap between words instead of being cut, and a session of several hundred alerts
/// gives a complete, paginated report with the explanations that were requested.
/// </summary>
public sealed class PdfReportTests
{
    private const string OfflineReason =
        "Layers: ML + TEMPORAL · top feature msg_frequency, timing=1.630, payload=0.000, ml=0.535, persistence=1.000";

    [Fact]
    public void ParseReason_SplitsLayersFeatureAndScores()
    {
        var p = PdfReportBuilder.ParseReason(OfflineReason);
        Assert.Equal(new[] { "ML", "TEMPORAL" }, p.Layers);
        Assert.Equal("msg_frequency", p.TopFeature);
        Assert.Equal(1.630, p.Scores["timing"], 3);
        Assert.Equal(0.535, p.Scores["ml"], 3);
        Assert.Equal(1.000, p.Scores["persistence"], 3);
    }

    [Fact]
    public void ParseReason_ReadsRuntimeReasonsWithoutLayers()
    {
        var p = PdfReportBuilder.ParseReason("timing=2.000, payload=0.252, ml=1.000, persistence=1.000, freq=0Hz, can_id_entropy=1.666");
        Assert.Empty(p.Layers);
        Assert.Equal(0.252, p.Scores["payload"], 3);
        Assert.True(p.IsStructured);
    }

    [Fact]
    public void ParseReason_KeepsFreeTextAsIs()
    {
        var p = PdfReportBuilder.ParseReason("identifier 0x666 is not defined in the DBC of the Arduino bench rig profile");
        Assert.False(p.IsStructured);
        Assert.StartsWith("identifier 0x666", p.Raw);
    }

    [Fact]
    public void Labels_UsePlainWords_AndNeverCallAPatternAnAttack()
    {
        Assert.Equal("Temporal pattern", PdfReportBuilder.HumanLayer("TEMPORAL"));
        Assert.Equal("Burst", PdfReportBuilder.HumanPattern("DOS_BURST"));
        Assert.Equal("Evaluated on a holdout recording", PdfReportBuilder.HumanStatus("clean_holdout_evaluated"));
        Assert.DoesNotContain("attack", PdfReportBuilder.HumanPattern("DOS_BURST"), StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void Wrap_BreaksBetweenWords_NotInsideThem()
    {
        using var doc = new PdfSharp.Pdf.PdfDocument();
        var page = doc.AddPage();
        using var g = PdfSharp.Drawing.XGraphics.FromPdfPage(page);
        var font = new PdfSharp.Drawing.XFont("Arial", 7.5);
        var lines = PdfReportBuilder.Wrap(g, "Top feature: variation of the time between frames · Burst", font, 120);
        Assert.True(lines.Count > 1);
        var words = "Top feature: variation of the time between frames · Burst".Split(' ');
        Assert.All(lines.SelectMany(l => l.Split(' ')), w => Assert.Contains(w, words));
    }

    [Fact]
    public void Build_WritesAPaginatedReportWithEveryAlert()
    {
        var alerts = Enumerable.Range(0, 339).Select(i => new AlertDetailItem
        {
            Index = i,
            Time = TimeSpan.FromMilliseconds(22976 - i * 61).ToString(@"hh\:mm\:ss\.fff"),
            CanId = i % 3 == 0 ? "0x063" : "0x0FB",
            Severity = i % 40 == 0 ? "CRITICAL" : (i % 2 == 0 ? "WARNING" : "INFO"),
            Score = 0.5 + (i % 40) / 100.0,
            AttackType = i % 10 == 0 ? "DOS_BURST" : "ML",
            Reason = OfflineReason,
        }).ToList();
        alerts[0].ExplanationSummary = "Repeated identical payload on CAN-ID 0x063 indicates a potential stuck ECU or replayed frames.";
        alerts[0].ExplanationRecommendation = "Check that the ECU is alive and sending fresh values.";

        var path = Path.Combine(Path.GetTempPath(), $"canvision_report_test_{Guid.NewGuid():N}.pdf");
        try
        {
            PdfReportBuilder.Build(alerts, path, new PdfReportContext
            {
                RecordingName = "canbus_turningon_quickly.csv",
                ModelName = "Jaguar I-PACE",
                ModelStatus = "clean_holdout_evaluated",
                AnalyzedRows = 50361, ScoredFrames = 40477, FlaggedFrames = 1249, UnresolvedFrames = 9884,
                UnresolvedReasons = new Dictionary<string, int> { ["sparse_id"] = 8451, ["warmup"] = 1368, ["unseen_id"] = 65 },
            });
            Assert.True(File.Exists(path));
            using var pdf = PdfReader.Open(path, PdfDocumentOpenMode.Import);
            Assert.True(pdf.PageCount >= 5, $"only {pdf.PageCount} pages for 339 alerts");
        }
        finally
        {
            if (File.Exists(path)) File.Delete(path);
        }
    }
}
