using System;
using System.Collections.Generic;
using System.Linq;
using CANvision.Native.Models;
using PdfSharp.Drawing;
using PdfSharp.Pdf;

namespace CANvision.Native.Services;

internal static class PdfReportBuilder
{
    // A4 in points (72pt = 1 inch)
    private const double PageW   = 595.0;
    private const double PageH   = 842.0;
    private const double MarginX = 36.0;
    private const double UseW    = PageW - 2 * MarginX;   // 523pt
    private const double RowH    = 20.0;

    // Column widths — must sum to UseW (523)
    private static readonly double[] ColW = { 20, 60, 52, 58, 82, 38, 213 };
    private static readonly string[] ColHeaders = { "#", "TIME", "CAN-ID", "SEVERITY", "ATTACK TYPE", "SCORE", "REASON" };

    private static readonly XColor ColCyan    = XColor.FromArgb(0x00, 0xC8, 0xC8);
    private static readonly XColor ColRed     = XColor.FromArgb(0xFF, 0x40, 0x40);
    private static readonly XColor ColOrange  = XColor.FromArgb(0xFF, 0x8C, 0x3A);
    private static readonly XColor ColYellow  = XColor.FromArgb(0xFF, 0xD9, 0x4A);
    private static readonly XColor ColGreen   = XColor.FromArgb(0x56, 0xF0, 0xAC);
    private static readonly XColor DarkHeader = XColor.FromArgb(0x0A, 0x12, 0x1A);
    private static readonly XColor RowEven    = XColor.FromArgb(0xF4, 0xF8, 0xF8);
    private static readonly XColor RowOdd     = XColor.FromArgb(0xE8, 0xF2, 0xF2);

    public static void Build(IReadOnlyList<AlertDetailItem> alerts, string path, DateTime generated)
    {
        var doc = new PdfDocument();
        doc.Info.Title   = "CANvision IDS — Alert Report";
        doc.Info.Author  = "CANvision Native";
        doc.Info.Subject = $"Alert Report {generated:yyyy-MM-dd HH:mm}";

        int critical = alerts.Count(a => a.Severity == "CRITICAL");
        int high     = alerts.Count(a => a.Severity is "HIGH" or "WARNING");
        int low      = alerts.Count - critical - high;

        int pageNum = 1;
        double y = AddFirstPage(doc, alerts.Count, critical, high, low, generated, pageNum);

        for (int i = 0; i < alerts.Count; i++)
        {
            var page = doc.Pages[doc.PageCount - 1];
            var gfx  = XGraphics.FromPdfPage(page);

            if (y + RowH > PageH - 32)
            {
                gfx.Dispose();
                pageNum++;
                y = AddContinuationPage(doc, pageNum);
                gfx = XGraphics.FromPdfPage(doc.Pages[doc.PageCount - 1]);
            }

            DrawAlertRow(gfx, alerts[i], i, y);
            y += RowH;
            gfx.Dispose();
        }

        doc.Save(path);
    }

    // Returns the Y position after summary — ready for first table row
    private static double AddFirstPage(PdfDocument doc, int total, int critical, int high, int low, DateTime generated, int pageNum)
    {
        var page = doc.AddPage();
        page.Size = PdfSharp.PageSize.A4;
        using var gfx = XGraphics.FromPdfPage(page);

        var fTitle = new XFont("Arial", 15, XFontStyle.Bold);
        var fSub   = new XFont("Arial", 8,  XFontStyle.Regular);
        var fH     = new XFont("Arial", 8,  XFontStyle.Bold);
        var fBody  = new XFont("Arial", 7.5, XFontStyle.Regular);

        // ── Header band ──────────────────────────────────────────────────────
        gfx.DrawRectangle(new XSolidBrush(DarkHeader), 0, 0, PageW, 58);
        gfx.DrawString("CANVISION IDS", fTitle, new XSolidBrush(ColCyan), MarginX, 26);
        gfx.DrawString("INTRUSION DETECTION SYSTEM  —  ALERT REPORT", fSub, XBrushes.LightGray, MarginX, 44);
        gfx.DrawString($"Generated: {generated:yyyy-MM-dd  HH:mm:ss}", fSub, XBrushes.Gray, PageW - 195, 44);

        // ── Summary box ───────────────────────────────────────────────────────
        double y = 74;
        gfx.DrawString("ANALYSIS SUMMARY", fH, XBrushes.Black, MarginX, y);
        y += 5;
        double sumH = 34;
        gfx.DrawRectangle(XPens.LightGray, new XRect(MarginX, y, UseW, sumH));

        var cells = new (string label, string value, XColor color)[]
        {
            ("TOTAL ALERTS",    total.ToString(),    DarkHeader),
            ("CRITICAL",        critical.ToString(), ColRed),
            ("HIGH / WARNING",  high.ToString(),     ColOrange),
            ("LOW",             low.ToString(),      ColGreen),
        };

        double cellW = UseW / cells.Length;
        for (int i = 0; i < cells.Length; i++)
        {
            double cx = MarginX + i * cellW;
            if (i > 0)
                gfx.DrawLine(XPens.LightGray, cx, y, cx, y + sumH);
            gfx.DrawString(cells[i].label, fBody, XBrushes.DarkGray, cx + 5, y + 11);
            var fVal = new XFont("Arial", 13, XFontStyle.Bold);
            gfx.DrawString(cells[i].value, fVal, new XSolidBrush(cells[i].color), cx + 5, y + 29);
        }

        y += sumH + 12;

        // ── Table heading ─────────────────────────────────────────────────────
        gfx.DrawString("ALERT DETAILS", fH, XBrushes.Black, MarginX, y);
        y += 6;
        DrawTableHeader(gfx, y);
        y += 15;

        DrawFooter(gfx, pageNum);
        return y;
    }

    private static double AddContinuationPage(PdfDocument doc, int pageNum)
    {
        var page = doc.AddPage();
        page.Size = PdfSharp.PageSize.A4;
        using var gfx = XGraphics.FromPdfPage(page);

        gfx.DrawRectangle(new XSolidBrush(DarkHeader), 0, 0, PageW, 28);
        var fSub = new XFont("Arial", 7, XFontStyle.Regular);
        gfx.DrawString("CANVISION IDS  —  ALERT REPORT (continued)", fSub, new XSolidBrush(ColCyan), MarginX, 18);

        double y = 38;
        DrawTableHeader(gfx, y);
        DrawFooter(gfx, pageNum);
        return y + 15;
    }

    private static void DrawTableHeader(XGraphics gfx, double y)
    {
        var fH = new XFont("Arial", 7.5, XFontStyle.Bold);
        gfx.DrawRectangle(new XSolidBrush(DarkHeader), MarginX, y, UseW, 14);
        double x = MarginX;
        for (int i = 0; i < ColHeaders.Length; i++)
        {
            gfx.DrawString(ColHeaders[i], fH, new XSolidBrush(ColCyan), x + 2, y + 10);
            x += ColW[i];
        }
    }

    private static void DrawAlertRow(XGraphics gfx, AlertDetailItem a, int rowIndex, double y)
    {
        var rowBg = rowIndex % 2 == 0 ? RowEven : RowOdd;
        gfx.DrawRectangle(new XSolidBrush(rowBg), MarginX, y, UseW, RowH);

        var sevColor = a.Severity switch
        {
            "CRITICAL" => ColRed,
            "HIGH"     => ColOrange,
            "WARNING"  => ColYellow,
            _          => ColGreen,
        };

        var fMono   = new XFont("Courier New", 7,   XFontStyle.Regular);
        var fSev    = new XFont("Courier New", 7,   XFontStyle.Bold);
        var fReason = new XFont("Arial",       6.5, XFontStyle.Regular);

        // Two-line reason: up to 55 chars per line (≈ full column width at 6.5pt)
        string r     = string.IsNullOrEmpty(a.Reason) ? "" : a.Reason;
        string line1 = r.Length > 55 ? r.Substring(0, 55) : r;
        string line2 = r.Length > 55
            ? (r.Length > 110 ? r.Substring(55, 55) + "…" : r.Substring(55))
            : "";

        double x     = MarginX;
        double midY  = y + RowH / 2.0;
        double textY = midY + 2.5;                          // single-line fields — vertically centred
        double rY1   = string.IsNullOrEmpty(line2) ? textY : y + 8.0;   // reason line 1
        double rY2   = y + 16.0;                            // reason line 2

        gfx.DrawString($"{rowIndex + 1}", fMono, XBrushes.Gray,                  x + 2, textY); x += ColW[0];
        gfx.DrawString(a.Time,            fMono, XBrushes.DarkGray,              x + 2, textY); x += ColW[1];
        gfx.DrawString(a.CanId,           fMono, XBrushes.DarkSlateGray,         x + 2, textY); x += ColW[2];
        gfx.DrawString(a.Severity,        fSev,  new XSolidBrush(sevColor),      x + 2, textY); x += ColW[3];
        gfx.DrawString(a.AttackType,      fMono, XBrushes.DarkGray,              x + 2, textY); x += ColW[4];
        gfx.DrawString($"{a.Score:F3}",   fMono, XBrushes.DarkGray,              x + 2, textY); x += ColW[5];
        gfx.DrawString(line1,             fReason, XBrushes.DimGray,             x + 2, rY1);
        if (!string.IsNullOrEmpty(line2))
            gfx.DrawString(line2,         fReason, XBrushes.DimGray,             x + 2, rY2);
    }

    private static void DrawFooter(XGraphics gfx, int pageNum)
    {
        var fFooter = new XFont("Arial", 7, XFontStyle.Regular);
        gfx.DrawLine(XPens.LightGray, MarginX, PageH - 22, PageW - MarginX, PageH - 22);
        gfx.DrawString("CANvision Native — CAN Bus Intrusion Detection System", fFooter, XBrushes.Gray, MarginX, PageH - 10);
        gfx.DrawString($"Page {pageNum}", fFooter, XBrushes.Gray, PageW - 65, PageH - 10);
    }
}
