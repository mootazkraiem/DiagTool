using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using CANvision.Native.Models;
using PdfSharp.Drawing;
using PdfSharp.Pdf;

namespace CANvision.Native.Services;

/// <summary>What the report says about the session the alerts come from. Counts are
/// -1 (or empty) when the session has no offline analysis summary, and the report
/// then says "Not available" instead of printing a zero.</summary>
internal sealed class PdfReportContext
{
    public DateTime Generated { get; set; } = DateTime.Now;
    public string RecordingName { get; set; } = string.Empty;
    public string ModelName { get; set; } = string.Empty;
    /// <summary>Backend model status (model_status.py), e.g. clean_holdout_evaluated.</summary>
    public string ModelStatus { get; set; } = string.Empty;
    public int AnalyzedRows { get; set; } = -1;
    public int ScoredFrames { get; set; } = -1;
    public int FlaggedFrames { get; set; } = -1;
    public int UnresolvedFrames { get; set; } = -1;
    public IReadOnlyDictionary<string, int> UnresolvedReasons { get; set; } = new Dictionary<string, int>();
}

/// <summary>The parts of an alert reason string, e.g.
/// "Layers: ML + TEMPORAL · top feature msg_frequency, timing=1.630, payload=0.000, ml=0.535, persistence=1.000".</summary>
internal sealed class ParsedReason
{
    public List<string> Layers { get; } = new();
    public string TopFeature { get; set; } = string.Empty;
    public Dictionary<string, double> Scores { get; } = new(StringComparer.OrdinalIgnoreCase);
    public string Raw { get; set; } = string.Empty;
    public bool IsStructured => Layers.Count > 0 || TopFeature.Length > 0 || Scores.Count > 0;
}

internal static class PdfReportBuilder
{
    // ── page geometry (points, A4) ───────────────────────────────────────────
    private const double PageW = 595.0, PageH = 842.0;
    private const double Margin = 42.0, Bottom = 56.0;
    private const double UseW = PageW - 2 * Margin;                     // 511

    // # | Time | CAN ID | Severity | Score | Detection layers | Details — sums to UseW
    private static readonly double[] ColW = { 22, 60, 44, 60, 34, 92, 199 };
    private static readonly string[] ColHeaders = { "#", "TIME", "CAN ID", "SEVERITY", "SCORE", "DETECTION LAYERS", "TOP FEATURE AND LAYER SCORES" };

    // ── palette: dark text on white, colour only where it carries meaning ───
    private static readonly XColor Ink = XColor.FromArgb(0x1D, 0x29, 0x39);
    private static readonly XColor Muted = XColor.FromArgb(0x66, 0x70, 0x85);
    private static readonly XColor Rule = XColor.FromArgb(0xE4, 0xE7, 0xEC);
    private static readonly XColor Zebra = XColor.FromArgb(0xF9, 0xFA, 0xFB);
    private static readonly XColor HeadBg = XColor.FromArgb(0xF2, 0xF4, 0xF7);
    private static readonly XColor Accent = XColor.FromArgb(0x0E, 0x74, 0x90);
    private static readonly XColor NoteBg = XColor.FromArgb(0xF0, 0xF9, 0xFF);

    private static readonly string[] SeverityOrder = { "CRITICAL", "HIGH", "WARNING", "MEDIUM", "LOW", "INFO" };

    private static XColor SeverityColor(string severity) => (severity ?? string.Empty).ToUpperInvariant() switch
    {
        "CRITICAL" => XColor.FromArgb(0xB4, 0x23, 0x18),
        "HIGH" => XColor.FromArgb(0xC4, 0x32, 0x0A),
        "WARNING" or "WARN" or "MEDIUM" => XColor.FromArgb(0xB5, 0x47, 0x08),
        _ => XColor.FromArgb(0x47, 0x54, 0x67),
    };

    private static XFont Font(double size, XFontStyle style = XFontStyle.Regular, string family = "Arial")
        => new(family, size, style, new XPdfFontOptions(PdfFontEncoding.Unicode));

    /// <summary>Kept for callers that only know the time of the report.</summary>
    public static void Build(IReadOnlyList<AlertDetailItem> alerts, string path, DateTime generated)
        => Build(alerts, path, new PdfReportContext { Generated = generated });

    public static void Build(IReadOnlyList<AlertDetailItem> alerts, string path, PdfReportContext context)
    {
        var doc = new PdfDocument();
        doc.Info.Title = "CANvisionNative anomaly report";
        doc.Info.Author = "CANvisionNative";
        doc.Info.Subject = string.IsNullOrWhiteSpace(context.RecordingName)
            ? $"Anomaly report {context.Generated:yyyy-MM-dd HH:mm}"
            : $"Anomaly report of {context.RecordingName}";

        // Chronological order reads better in a report than the newest-first list on screen.
        var ordered = alerts.Select((a, i) => (a, i))
                            .OrderBy(t => t.a.Time, StringComparer.Ordinal)
                            .ThenBy(t => t.i)
                            .Select(t => t.a)
                            .ToList();

        var w = new Writer(doc);
        DrawTitle(w, context);
        DrawSession(w, context);
        DrawSummary(w, ordered);
        DrawNote(w);
        DrawTopIdentifiers(w, ordered);
        DrawAlertTable(w, ordered);
        DrawExplanations(w, ordered);
        w.Close();

        DrawFooters(doc, context);
        doc.Save(path);
    }

    // ── page handling ────────────────────────────────────────────────────────

    private sealed class Writer
    {
        private readonly PdfDocument doc;
        public XGraphics G = null!;
        public double Y;

        public Writer(PdfDocument doc)
        {
            this.doc = doc;
            NewPage(first: true);
        }

        public void NewPage(bool first = false)
        {
            G?.Dispose();
            var page = doc.AddPage();
            page.Size = PdfSharp.PageSize.A4;
            G = XGraphics.FromPdfPage(page);
            Y = Margin;
            if (!first)
            {
                G.DrawString("CANvisionNative  ·  Anomaly report (continued)", Font(7.5), new XSolidBrush(Muted), Margin, Y + 7);
                Y += 20;
            }
        }

        /// <summary>Starts a new page when <paramref name="height"/> does not fit.</summary>
        public bool Ensure(double height)
        {
            if (Y + height <= PageH - Bottom) return false;
            NewPage();
            return true;
        }

        public void Close() => G?.Dispose();
    }

    private static void SectionHeading(Writer w, string text, double spaceAfter = 8)
    {
        w.Ensure(40);
        w.G.DrawString(text, Font(11, XFontStyle.Bold), new XSolidBrush(Ink), Margin, w.Y + 11);
        w.Y += 16 + spaceAfter;
    }

    // ── sections ─────────────────────────────────────────────────────────────

    private static void DrawTitle(Writer w, PdfReportContext c)
    {
        var g = w.G;
        g.DrawRectangle(new XSolidBrush(Accent), 0, 0, PageW, 5);
        g.DrawString("CANvisionNative", Font(20, XFontStyle.Bold), new XSolidBrush(Ink), Margin, w.Y + 18);
        g.DrawString("Anomaly report", Font(11), new XSolidBrush(Accent), Margin, w.Y + 36);
        var stamp = "Generated " + c.Generated.ToString("d MMMM yyyy, HH:mm", CultureInfo.InvariantCulture);
        g.DrawString(stamp, Font(8.5), new XSolidBrush(Muted), new XRect(Margin, w.Y + 26, UseW, 12), XStringFormats.TopRight);
        w.Y += 48;
        g.DrawLine(new XPen(Rule, 1), Margin, w.Y, PageW - Margin, w.Y);
        w.Y += 18;
    }

    private static void DrawSession(Writer w, PdfReportContext c)
    {
        SectionHeading(w, "Session");
        string na = "Not available";
        string Count(int n) => n >= 0 ? n.ToString("N0", CultureInfo.InvariantCulture) : na;

        string flagged = na;
        if (c.FlaggedFrames >= 0 && c.ScoredFrames > 0)
            flagged = $"{Count(c.FlaggedFrames)}  ({((double)c.FlaggedFrames / c.ScoredFrames * 100.0).ToString("F2", CultureInfo.InvariantCulture)}% of the scored frames)";

        string unresolved = c.UnresolvedFrames >= 0 && c.AnalyzedRows > 0 ? Count(c.UnresolvedFrames) : na;
        if (c.UnresolvedFrames > 0 && c.UnresolvedReasons.Count > 0)
            unresolved += "  (" + string.Join(", ", c.UnresolvedReasons.OrderByDescending(r => r.Value)
                .Select(r => $"{HumanReason(r.Key)} {r.Value.ToString("N0", CultureInfo.InvariantCulture)}")) + ")";

        var left = new (string key, string value)[]
        {
            ("Recording", string.IsNullOrWhiteSpace(c.RecordingName) ? na : c.RecordingName),
            ("Selected model", string.IsNullOrWhiteSpace(c.ModelName) ? na : c.ModelName),
            ("Model status", string.IsNullOrWhiteSpace(c.ModelStatus) ? na : HumanStatus(c.ModelStatus)),
        };
        var right = new (string key, string value)[]
        {
            ("Frames analysed", c.AnalyzedRows > 0 ? Count(c.AnalyzedRows) : na),
            ("Frames scored", c.AnalyzedRows > 0 ? Count(c.ScoredFrames) : na),
            ("Frames flagged", flagged),
            ("Frames unresolved", unresolved),
        };

        double colW = (UseW - 16) / 2, keyW = 86;
        double yl = KeyValueColumn(w.G, left, Margin, w.Y, colW, keyW);
        double yr = KeyValueColumn(w.G, right, Margin + colW + 16, w.Y, colW, keyW);
        w.Y = Math.Max(yl, yr) + 14;
    }

    private static double KeyValueColumn(XGraphics g, (string key, string value)[] rows, double x, double y, double width, double keyW)
    {
        var fk = Font(8.5);
        var fv = Font(8.5, XFontStyle.Bold);
        foreach (var (key, value) in rows)
        {
            var lines = Wrap(g, value, fv, width - keyW);
            g.DrawString(key, fk, new XSolidBrush(Muted), x, y + 9);
            for (int i = 0; i < lines.Count; i++)
                g.DrawString(lines[i], fv, new XSolidBrush(Ink), x + keyW, y + 9 + i * 11);
            y += 11 * lines.Count + 5;
        }
        return y;
    }

    private static void DrawSummary(Writer w, List<AlertDetailItem> alerts)
    {
        SectionHeading(w, "Summary");
        var cards = new List<(string label, int value, XColor color)> { ("ALERTS", alerts.Count, Accent) };
        foreach (var sev in SeverityOrder)
        {
            int n = alerts.Count(a => string.Equals(a.Severity, sev, StringComparison.OrdinalIgnoreCase));
            if (n > 0) cards.Add((sev, n, SeverityColor(sev)));
        }
        foreach (var other in alerts.Select(a => (a.Severity ?? "").ToUpperInvariant()).Distinct()
                                    .Where(s => s.Length > 0 && !SeverityOrder.Contains(s)))
            cards.Add((other, alerts.Count(a => string.Equals(a.Severity, other, StringComparison.OrdinalIgnoreCase)), SeverityColor(other)));

        const double gap = 8, h = 46;
        double cw = (UseW - gap * (cards.Count - 1)) / cards.Count;
        for (int i = 0; i < cards.Count; i++)
        {
            double x = Margin + i * (cw + gap);
            w.G.DrawRoundedRectangle(new XPen(Rule, 1), XBrushes.White, new XRect(x, w.Y, cw, h), new XSize(6, 6));
            w.G.DrawRectangle(new XSolidBrush(cards[i].color), x, w.Y + 8, 3, h - 16);
            w.G.DrawString(cards[i].label, Font(7.5, XFontStyle.Bold), new XSolidBrush(Muted), x + 12, w.Y + 17);
            w.G.DrawString(cards[i].value.ToString("N0", CultureInfo.InvariantCulture), Font(17, XFontStyle.Bold),
                           new XSolidBrush(Ink), x + 12, w.Y + 37);
        }
        w.Y += h + 12;
    }

    private static void DrawNote(Writer w)
    {
        const string note = "A flagged frame is unusual compared with the training recordings of the selected model; it is not a "
                          + "confirmed attack. Frames that no model could score are reported as unresolved and are not counted as "
                          + "normal. An alert can group several flagged frames, so there are fewer alerts than flagged frames.";
        var f = Font(8, XFontStyle.Italic);
        var lines = Wrap(w.G, note, f, UseW - 20);
        double h = lines.Count * 10.5 + 12;
        w.G.DrawRoundedRectangle(new XSolidBrush(NoteBg), Margin, w.Y, UseW, h, 6, 6);
        for (int i = 0; i < lines.Count; i++)
            w.G.DrawString(lines[i], f, new XSolidBrush(Muted), Margin + 10, w.Y + 14 + i * 10.5);
        w.Y += h + 18;
    }

    private static void DrawTopIdentifiers(Writer w, List<AlertDetailItem> alerts)
    {
        if (alerts.Count == 0) return;
        var top = alerts.GroupBy(a => a.CanId)
                        .Select(g => new
                        {
                            Id = g.Key,
                            Count = g.Count(),
                            Max = g.Max(a => a.Score),
                            Layers = string.Join(", ", g.SelectMany(a => ParseReason(a.Reason).Layers)
                                                        .GroupBy(l => l).OrderByDescending(l => l.Count())
                                                        .Take(3).Select(l => HumanLayer(l.Key))),
                        })
                        .OrderByDescending(t => t.Count).ThenByDescending(t => t.Max)
                        .Take(8).ToList();

        SectionHeading(w, "Identifiers with the most alerts");
        double[] cw = { 70, 60, 80, UseW - 210 };
        string[] head = { "CAN ID", "ALERTS", "HIGHEST SCORE", "MOST FREQUENT DETECTION LAYERS" };
        TableHeader(w.G, w.Y, cw, head);
        w.Y += 16;
        var f = Font(8.5);
        for (int i = 0; i < top.Count; i++)
        {
            const double rh = 15;
            if (i % 2 == 1) w.G.DrawRectangle(new XSolidBrush(Zebra), Margin, w.Y, UseW, rh);
            double x = Margin;
            Cell(w.G, top[i].Id, Font(8.5, XFontStyle.Bold), Ink, x, w.Y, cw[0], rh); x += cw[0];
            Cell(w.G, top[i].Count.ToString("N0", CultureInfo.InvariantCulture), f, Ink, x, w.Y, cw[1], rh); x += cw[1];
            Cell(w.G, top[i].Max.ToString("F3", CultureInfo.InvariantCulture), f, Ink, x, w.Y, cw[2], rh); x += cw[2];
            Cell(w.G, string.IsNullOrEmpty(top[i].Layers) ? "Not available" : top[i].Layers, f, Muted, x, w.Y, cw[3], rh);
            w.G.DrawLine(new XPen(Rule, 0.6), Margin, w.Y + rh, PageW - Margin, w.Y + rh);
            w.Y += rh;
        }
        w.Y += 20;
    }

    private static void DrawAlertTable(Writer w, List<AlertDetailItem> alerts)
    {
        SectionHeading(w, $"Alerts ({alerts.Count.ToString("N0", CultureInfo.InvariantCulture)})", 4);
        w.G.DrawString("Score: normalised model score for an offline analysis (flagged above 0.50), fused score for replay and live capture.",
                       Font(7.5, XFontStyle.Italic), new XSolidBrush(Muted), Margin, w.Y + 7);
        w.Y += 16;
        TableHeader(w.G, w.Y, ColW, ColHeaders);
        w.Y += 16;

        var fCell = Font(8);
        var fBold = Font(8, XFontStyle.Bold);
        var fDetail = Font(7.5);
        var fScores = Font(7);
        for (int i = 0; i < alerts.Count; i++)
        {
            var a = alerts[i];
            var p = ParseReason(a.Reason);
            string layers = p.Layers.Count > 0 ? string.Join(", ", p.Layers.Select(HumanLayer)) : HumanPattern(a.AttackType);
            string pattern = HumanPattern(a.AttackType);
            var detailLines = new List<string>();
            if (p.IsStructured)
            {
                var feature = p.TopFeature.Length > 0 ? "Top feature: " + HumanFeature(p.TopFeature) : string.Empty;
                if (pattern.Length > 0 && pattern != "Model" && !layers.Contains(pattern))
                    feature = feature.Length > 0 ? $"{feature} · {pattern}" : pattern;
                if (feature.Length > 0) detailLines.AddRange(Wrap(w.G, feature, fDetail, ColW[6] - 8));
            }
            else
            {
                detailLines.AddRange(Wrap(w.G, string.IsNullOrWhiteSpace(a.Reason) ? "Not available" : a.Reason, fDetail, ColW[6] - 8));
            }
            var scoreLines = p.Scores.Count > 0 ? Wrap(w.G, LayerScores(p), fScores, ColW[6] - 8) : new List<string>();
            var layerLines = Wrap(w.G, layers, fCell, ColW[5] - 8);

            int lineCount = Math.Max(layerLines.Count, detailLines.Count + scoreLines.Count);
            double rh = Math.Max(18, 5 + lineCount * 9.5);

            if (w.Ensure(rh))
            {
                TableHeader(w.G, w.Y, ColW, ColHeaders);
                w.Y += 16;
            }
            if (i % 2 == 1) w.G.DrawRectangle(new XSolidBrush(Zebra), Margin, w.Y, UseW, rh);

            const double lh = 9.5;
            double x = Margin, top = w.Y + 3;
            Cell(w.G, (i + 1).ToString(CultureInfo.InvariantCulture), fCell, Muted, x, top, ColW[0], lh); x += ColW[0];
            Cell(w.G, a.Time, fCell, Ink, x, top, ColW[1], lh); x += ColW[1];
            Cell(w.G, a.CanId, fBold, Ink, x, top, ColW[2], lh); x += ColW[2];
            Badge(w.G, a.Severity, x + 4, top - 1); x += ColW[3];
            Cell(w.G, a.Score.ToString("F3", CultureInfo.InvariantCulture), fCell, Ink, x, top, ColW[4], lh); x += ColW[4];
            for (int l = 0; l < layerLines.Count; l++)
                Cell(w.G, layerLines[l], fCell, Ink, x, top + l * lh, ColW[5], lh);
            x += ColW[5];
            int line = 0;
            foreach (var d in detailLines) Cell(w.G, d, fDetail, Ink, x, top + line++ * lh, ColW[6], lh);
            foreach (var s in scoreLines) Cell(w.G, s, fScores, Muted, x, top + line++ * lh, ColW[6], lh);

            w.G.DrawLine(new XPen(Rule, 0.6), Margin, w.Y + rh, PageW - Margin, w.Y + rh);
            w.Y += rh;
        }
        w.Y += 20;
    }

    private static void DrawExplanations(Writer w, List<AlertDetailItem> alerts)
    {
        var explained = alerts.Select((a, i) => (a, n: i + 1))
                              .Where(t => !string.IsNullOrWhiteSpace(t.a.ExplanationSummary))
                              .ToList();
        if (explained.Count == 0) return;

        SectionHeading(w, "Explanations requested during the session");
        var fHead = Font(8.5, XFontStyle.Bold);
        var fBody = Font(8.5);
        var fLabel = Font(8, XFontStyle.Bold);
        foreach (var (a, n) in explained)
        {
            var summary = Wrap(w.G, a.ExplanationSummary, fBody, UseW - 20);
            var recommendation = string.IsNullOrWhiteSpace(a.ExplanationRecommendation)
                ? new List<string>()
                : Wrap(w.G, a.ExplanationRecommendation, fBody, UseW - 20);
            double h = 22 + summary.Count * 11 + (recommendation.Count > 0 ? 14 + recommendation.Count * 11 : 0) + 8;
            w.Ensure(h);

            w.G.DrawRoundedRectangle(new XPen(Rule, 1), XBrushes.White, new XRect(Margin, w.Y, UseW, h), new XSize(6, 6));
            string head = $"Alert {n}  ·  {a.CanId}  ·  {a.Time}  ·  written by {HumanEngine(a.ExplanationMode)}";
            w.G.DrawString(head, fHead, new XSolidBrush(Ink), Margin + 10, w.Y + 15);
            double y = w.Y + 29;
            foreach (var l in summary) { w.G.DrawString(l, fBody, new XSolidBrush(Ink), Margin + 10, y); y += 11; }
            if (recommendation.Count > 0)
            {
                y += 3;
                w.G.DrawString("Recommendation", fLabel, new XSolidBrush(Accent), Margin + 10, y);
                y += 11;
                foreach (var l in recommendation) { w.G.DrawString(l, fBody, new XSolidBrush(Ink), Margin + 10, y); y += 11; }
            }
            w.Y += h + 8;
        }
    }

    private static void DrawFooters(PdfDocument doc, PdfReportContext c)
    {
        var f = Font(7.5);
        string left = "CANvisionNative  ·  Anomaly report" + (string.IsNullOrWhiteSpace(c.RecordingName) ? "" : "  ·  " + c.RecordingName);
        for (int i = 0; i < doc.PageCount; i++)
        {
            using var g = XGraphics.FromPdfPage(doc.Pages[i], XGraphicsPdfPageOptions.Append);
            double y = PageH - 34;
            g.DrawLine(new XPen(Rule, 0.8), Margin, y, PageW - Margin, y);
            g.DrawString(left, f, new XSolidBrush(Muted), Margin, y + 13);
            g.DrawString($"Page {i + 1} of {doc.PageCount}", f, new XSolidBrush(Muted),
                         new XRect(Margin, y + 5, UseW, 10), XStringFormats.TopRight);
        }
    }

    // ── drawing helpers ──────────────────────────────────────────────────────

    private static void TableHeader(XGraphics g, double y, double[] widths, string[] headers)
    {
        g.DrawRectangle(new XSolidBrush(HeadBg), Margin, y, widths.Sum(), 16);
        double x = Margin;
        for (int i = 0; i < headers.Length; i++)
        {
            g.DrawString(headers[i], Font(6.8, XFontStyle.Bold), new XSolidBrush(Muted),
                         new XRect(x + 4, y, widths[i] - 4, 16), XStringFormats.CenterLeft);
            x += widths[i];
        }
    }

    private static void Cell(XGraphics g, string text, XFont f, XColor color, double x, double y, double w, double h)
        => g.DrawString(text ?? string.Empty, f, new XSolidBrush(color), new XRect(x + 4, y, w - 6, h), XStringFormats.CenterLeft);

    private static void Badge(XGraphics g, string severity, double x, double y)
    {
        var label = string.IsNullOrWhiteSpace(severity) ? "N/A" : severity.ToUpperInvariant();
        var f = Font(6.8, XFontStyle.Bold);
        double w = g.MeasureString(label, f).Width + 10;
        g.DrawRoundedRectangle(new XSolidBrush(SeverityColor(label)), x, y, w, 12, 6, 6);
        g.DrawString(label, f, XBrushes.White, new XRect(x, y, w, 12), XStringFormats.Center);
    }

    /// <summary>Splits <paramref name="text"/> into lines no wider than <paramref name="width"/>,
    /// breaking between words; a word longer than a line is split between characters.</summary>
    internal static List<string> Wrap(XGraphics g, string text, XFont font, double width)
    {
        var lines = new List<string>();
        if (string.IsNullOrWhiteSpace(text)) { lines.Add(string.Empty); return lines; }
        var current = string.Empty;
        foreach (var word in text.Split(new[] { ' ' }, StringSplitOptions.RemoveEmptyEntries))
        {
            var candidate = current.Length == 0 ? word : current + " " + word;
            if (g.MeasureString(candidate, font).Width <= width) { current = candidate; continue; }
            if (current.Length > 0) lines.Add(current);
            current = word;
            while (g.MeasureString(current, font).Width > width && current.Length > 1)
            {
                int cut = current.Length - 1;
                while (cut > 1 && g.MeasureString(current.Substring(0, cut), font).Width > width) cut--;
                lines.Add(current.Substring(0, cut));
                current = current.Substring(cut);
            }
        }
        if (current.Length > 0) lines.Add(current);
        return lines;
    }

    // ── reason parsing and plain-language labels ─────────────────────────────

    internal static ParsedReason ParseReason(string reason)
    {
        var p = new ParsedReason { Raw = reason ?? string.Empty };
        if (string.IsNullOrWhiteSpace(reason)) return p;

        string rest = (reason ?? string.Empty).Trim();
        if (rest.StartsWith("Layers:", StringComparison.OrdinalIgnoreCase))
        {
            rest = rest.Substring("Layers:".Length);
            int dot = rest.IndexOf('·');
            int comma = rest.IndexOf(',');
            int end = dot >= 0 ? dot : (comma >= 0 ? comma : rest.Length);
            foreach (var layer in rest.Substring(0, end).Split('+'))
                if (layer.Trim().Length > 0) p.Layers.Add(layer.Trim().ToUpperInvariant());
            rest = rest.Substring(end).TrimStart('·', ' ');
        }

        foreach (var part in rest.Split(','))
        {
            var t = part.Trim();
            if (t.StartsWith("top feature", StringComparison.OrdinalIgnoreCase))
            {
                p.TopFeature = t.Substring("top feature".Length).Trim();
                continue;
            }
            int eq = t.IndexOf('=');
            if (eq > 0 && double.TryParse(t.Substring(eq + 1).Trim(), NumberStyles.Float, CultureInfo.InvariantCulture, out var v))
                p.Scores[t.Substring(0, eq).Trim()] = v;
        }
        return p;
    }

    private static string LayerScores(ParsedReason p)
    {
        var parts = new List<string>();
        foreach (var (key, label) in new[] { ("timing", "Timing"), ("payload", "Payload"), ("ml", "Model"), ("persistence", "Persistence") })
            if (p.Scores.TryGetValue(key, out var v))
                parts.Add($"{label} {v.ToString("F2", CultureInfo.InvariantCulture)}");
        return string.Join("  ·  ", parts);
    }

    internal static string HumanLayer(string layer) => (layer ?? string.Empty).ToUpperInvariant() switch
    {
        "ML" => "Model",
        "TEMPORAL" => "Temporal pattern",
        "PLAUSIBILITY" => "Plausibility",
        "FINGERPRINT" => "Timing fingerprint",
        "WHITELIST" => "Unknown identifier",
        "CORRELATION" => "Signal correlation",
        "TIMING" => "Timing",
        "PAYLOAD" => "Payload",
        "PERSISTENCE" => "Persistence",
        _ => Title(layer),
    };

    internal static string HumanPattern(string pattern) => (pattern ?? string.Empty).ToUpperInvariant() switch
    {
        "" or "UNKNOWN" => string.Empty,
        "ML" => "Model",
        // "dos_burst": a measured rate far above the identifier's baseline (temporal.py).
        // "alert_burst": several flagged frames merged into one alert (dedup.py), not a rate.
        "DOS_BURST" => "Burst",
        "ALERT_BURST" => "Alert burst",
        "RATE_SPIKE" => "Rate spike",
        "PAYLOAD_FREEZE" or "FROZEN_PAYLOAD" => "Frozen payload",
        _ => Title(pattern),
    };

    private static string HumanFeature(string feature) => (feature ?? string.Empty).ToLowerInvariant() switch
    {
        "msg_frequency" => "message frequency",
        "msg_rate" => "message rate",
        "time_diff" => "time since the previous frame",
        "rolling_mean_time_diff" => "mean time between frames",
        "rolling_std_time_diff" => "variation of the time between frames",
        "byte_diff" => "byte change",
        "rolling_mean_byte_diff" => "mean byte change",
        "rolling_std_byte_diff" => "variation of the byte change",
        "rolling_max_byte_diff" => "largest byte change",
        "changed_bytes_count" => "number of changed bytes",
        "payload_entropy" => "payload entropy",
        _ => (feature ?? string.Empty).Replace('_', ' '),
    };

    private static string HumanReason(string reason) => (reason ?? string.Empty).ToLowerInvariant() switch
    {
        "sparse_id" => "sparse identifier",
        "unseen_id" => "unseen identifier",
        "unmodelled_id" => "unmodelled identifier",
        "warmup" => "warmup",
        _ => (reason ?? string.Empty).Replace('_', ' '),
    };

    internal static string HumanStatus(string status) => (status ?? string.Empty).ToLowerInvariant() switch
    {
        "clean_holdout_evaluated" => "Evaluated on a holdout recording",
        "clean_unvalidated_no_holdout" => "Not validated (no holdout recording)",
        "clean_held_back" => "Held back after its evaluation",
        "unavailable_no_clean_model" => "No final model",
        "legacy" => "Model of the first design",
        "general" => "General model",
        _ => (status ?? string.Empty).Replace('_', ' '),
    };

    private static string HumanEngine(string mode) => (mode ?? string.Empty).ToLowerInvariant() switch
    {
        "gemini" => "Gemini",
        "ollama" => "a local Ollama model",
        _ => "the rule based template",
    };

    private static string Title(string? s)
    {
        if (s is null || s.Trim().Length == 0) return string.Empty;
        var t = s.Replace('_', ' ').ToLowerInvariant();
        return char.ToUpperInvariant(t[0]) + t.Substring(1);
    }
}
