using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;

namespace CANvision.Native.Services;

/// <summary>
/// Ground-truth labels for a replay log: a "&lt;name&gt;_gt.csv" file next to it with
/// "timestamp,attack_type" rows ("normal" or the attack name), as shipped with the
/// validation replays (validation_dos_replay.csv / validation_dos_gt.csv).
/// </summary>
internal static class GroundTruthLabels
{
    /// <summary>The label file for a log, or null when there is none.</summary>
    public static string? FindFor(string? logPath)
    {
        if (string.IsNullOrWhiteSpace(logPath)) return null;
        var dir = Path.GetDirectoryName(logPath) ?? string.Empty;
        var stem = Path.GetFileNameWithoutExtension(logPath);
        var candidates = new List<string>();
        if (stem.EndsWith("_replay", StringComparison.OrdinalIgnoreCase))
            candidates.Add(Path.Combine(dir, stem.Substring(0, stem.Length - "_replay".Length) + "_gt.csv"));
        candidates.Add(Path.Combine(dir, stem + "_gt.csv"));
        foreach (var candidate in candidates)
            if (File.Exists(candidate)) return candidate;
        return null;
    }

    /// <summary>
    /// Labelled attack spans in capture time: consecutive rows with the same
    /// non-normal label form one span; a normal row or a new label ends it.
    /// </summary>
    public static List<GroundTruthSpan> ReadSpans(string gtPath)
    {
        var rows = new List<(double Time, string Label)>();
        foreach (var line in File.ReadLines(gtPath))
        {
            var comma = line.IndexOf(',');
            if (comma <= 0) continue;
            if (!double.TryParse(line.Substring(0, comma).Trim(), NumberStyles.Float, CultureInfo.InvariantCulture, out var time))
                continue; // header
            rows.Add((time, line.Substring(comma + 1).Trim()));
        }
        rows = rows.OrderBy(r => r.Time).ToList();   // stable: equal timestamps keep file order

        var spans = new List<GroundTruthSpan>();
        GroundTruthSpan? open = null;
        foreach (var (time, label) in rows)
        {
            var isAttack = label.Length > 0 && !label.Equals("normal", StringComparison.OrdinalIgnoreCase);
            if (open is not null && (!isAttack || !open.Label.Equals(label, StringComparison.OrdinalIgnoreCase)))
            {
                spans.Add(open);
                open = null;
            }
            if (!isAttack) continue;
            if (open is null)
                open = new GroundTruthSpan(time, time, label);
            else
                open.End = time;
        }
        if (open is not null) spans.Add(open);
        return spans;
    }
}

internal sealed class GroundTruthSpan
{
    public GroundTruthSpan(double start, double end, string label)
    {
        Start = start;
        End = end;
        Label = label;
    }

    public double Start { get; }
    public double End { get; set; }
    public string Label { get; }
}
