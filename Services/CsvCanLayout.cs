using System.Globalization;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;

namespace CANvision.Native.Services;

internal enum CsvRadix
{
    Hex,
    Decimal,
}

/// <summary>
/// Column map for CAN logs exported as CSV with a header row.
///
/// Columns are located by header name, never by fixed position, so exports that
/// put other fields before the identifier (asammdf/CSS Electronics MF4 exports
/// start with <c>BusChannel</c>) are read correctly.
///
/// Numeric encodings are decided per column from evidence in the data, and only
/// fall back to the convention of the tool that writes the format when the
/// sampled values are ambiguous. This mirrors how the Python backend reads the
/// same files (backend/ml/state_based_pipeline.py: load_skoda_log,
/// load_ev_can_log), so the desktop playback and the ML analysis see the same
/// frames:
///
///   asammdf MF4 export    timestamps, ..BusChannel, ..ID, ..IDE, ..DLC, ..DataBytes
///                         decimal ID, DataBytes = "[ 3 34 70 ...]" decimal
///   SavvyCAN              Time Stamp, ID, Extended, [Dir,] Bus, LEN, D1..D8   hex
///   timestamp,can_id,b0.. hex unless the data shows otherwise (backend /analyze
///                         semantics; bytes such as "128" are decimal by evidence)
///
/// Headerless lines, candump and ASC are not handled here; they keep the
/// per-line parsers in <see cref="CanLogImportService"/>.
/// </summary>
internal sealed class CsvCanLayout
{
    private const long MaxCanId = 0x1FFFFFFF; // 29-bit extended identifier

    private static readonly string[] TimestampNames = { "timestamp", "timestamps", "time", "ts" };
    private static readonly string[] IdNames = { "id", "canid", "arbitrationid", "arbid", "identifier", "msgid", "messageid" };
    private static readonly string[] ChannelNames = { "buschannel", "bus", "channel", "ch" };
    private static readonly string[] ExtendedNames = { "ide", "extended", "isextendedid", "isextended" };
    // DataLength is the byte count; DLC is a length code (equal for classic CAN).
    private static readonly string[] LengthNames = { "datalength", "len", "length", "dlc" };
    private static readonly string[] DataArrayNames = { "databytes", "data", "payload", "bytes", "databyte" };

    private static readonly Regex ZeroBasedByteColumn = new(@"^(?:b|byte|data)(\d+)$", RegexOptions.Compiled);
    private static readonly Regex OneBasedByteColumn = new(@"^d(\d+)$", RegexOptions.Compiled);

    private CsvCanLayout(string formatName, int timestampIndex, int idIndex)
    {
        FormatName = formatName;
        TimestampIndex = timestampIndex;
        IdIndex = idIndex;
    }

    public string FormatName { get; }
    public int TimestampIndex { get; }
    public int IdIndex { get; }
    public int ChannelIndex { get; private set; } = -1;
    public int ExtendedIndex { get; private set; } = -1;
    public int LengthIndex { get; private set; } = -1;
    public int DataArrayIndex { get; private set; } = -1;
    public IReadOnlyList<int> ByteColumnIndexes { get; private set; } = Array.Empty<int>();
    public CsvRadix IdRadix { get; private set; }
    public CsvRadix ByteRadix { get; private set; }

    /// <summary>
    /// Reads the header and a sample of rows. Returns null when the file does not
    /// start with a recognisable CSV header (candump, ASC, headerless CSV, ...).
    /// </summary>
    public static CsvCanLayout? Detect(string filePath, int sampleRows = 500)
    {
        try
        {
            using var reader = new StreamReader(filePath, Encoding.UTF8, detectEncodingFromByteOrderMarks: true);
            string? line;
            CsvCanLayout? layout = null;
            var samples = new List<IReadOnlyList<string>>();
            while ((line = reader.ReadLine()) != null)
            {
                var trimmed = line.Trim();
                if (trimmed.Length == 0 || trimmed.StartsWith("#") || trimmed.StartsWith("//") || trimmed.StartsWith(";"))
                {
                    continue;
                }

                if (layout is null)
                {
                    layout = FromHeader(trimmed);
                    if (layout is null)
                    {
                        return null; // first meaningful line is data or another format
                    }

                    continue;
                }

                samples.Add(SplitFields(trimmed));
                if (samples.Count >= sampleRows)
                {
                    break;
                }
            }

            layout?.DecideRadix(samples);
            return layout;
        }
        catch (IOException)
        {
            return null;
        }
        catch (UnauthorizedAccessException)
        {
            return null;
        }
    }

    /// <summary>Builds a layout from a header line, or null if it is not a CAN CSV header.</summary>
    internal static CsvCanLayout? FromHeader(string headerLine)
    {
        var raw = SplitFields(headerLine);
        if (raw.Count < 3 || double.TryParse(raw[0].Trim(), NumberStyles.Float, CultureInfo.InvariantCulture, out _))
        {
            return null; // a numeric first field means a data row, not a header
        }

        var names = raw.Select(Normalize).ToList();
        var timestampIndex = FindFirst(names, TimestampNames);
        var idIndex = FindFirst(names, IdNames);
        if (timestampIndex < 0 || idIndex < 0)
        {
            return null;
        }

        var byteColumns = new List<(int Position, int Column, bool OneBased)>();
        for (var i = 0; i < names.Count; i++)
        {
            var zero = ZeroBasedByteColumn.Match(names[i]);
            if (zero.Success)
            {
                byteColumns.Add((int.Parse(zero.Groups[1].Value, CultureInfo.InvariantCulture), i, false));
                continue;
            }

            var one = OneBasedByteColumn.Match(names[i]);
            if (one.Success)
            {
                byteColumns.Add((int.Parse(one.Groups[1].Value, CultureInfo.InvariantCulture) - 1, i, true));
            }
        }

        var dataArrayIndex = FindFirst(names, DataArrayNames);
        if (dataArrayIndex < 0 && byteColumns.Count == 0)
        {
            return null; // no payload source
        }

        var formatName =
            headerLine.IndexOf("CAN_DataFrame", StringComparison.OrdinalIgnoreCase) >= 0 ? "asammdf-mf4-export"
            : byteColumns.Count > 0 && byteColumns.All(c => c.OneBased) ? "savvycan"
            : byteColumns.Count > 0 ? "canvision-csv"
            : "generic-header";

        var layout = new CsvCanLayout(formatName, timestampIndex, idIndex)
        {
            ChannelIndex = FindFirst(names, ChannelNames),
            ExtendedIndex = FindFirst(names, ExtendedNames),
            LengthIndex = FindFirst(names, LengthNames),
            DataArrayIndex = dataArrayIndex,
            ByteColumnIndexes = byteColumns.OrderBy(c => c.Position).Select(c => c.Column).ToList(),
        };

        // Convention of the producing tool; overridden by evidence in DecideRadix.
        // Without evidence: asammdf exports are decimal by construction (integer IDs,
        // uint8 arrays); everything else keeps the previous hex reading, which is also
        // how the backend /analyze fallback reads it (backend/data_processing/csv_frames.py).
        layout.IdRadix = formatName == "asammdf-mf4-export" ? CsvRadix.Decimal : CsvRadix.Hex;
        layout.ByteRadix = formatName == "asammdf-mf4-export" ? CsvRadix.Decimal : CsvRadix.Hex;
        return layout;
    }

    /// <summary>
    /// Settles ID and byte radix from sampled values. Hex letters are definitive;
    /// zero-padded identifiers (SavvyCAN "0000012D") are hex; identifiers that would
    /// exceed 29 bits if read as hex, and byte tokens of three digits, are decimal.
    /// Numpy-style "[ .. ]" byte arrays are decimal (that is how numpy prints uint8).
    /// </summary>
    internal void DecideRadix(IEnumerable<IReadOnlyList<string>> rows)
    {
        bool idHex = false, idDecimal = false, byteHex = false, byteDecimal = false;
        foreach (var fields in rows)
        {
            if (IdIndex < fields.Count)
            {
                var id = Unquote(fields[IdIndex]);
                if (id.Length > 0)
                {
                    if (id.StartsWith("0x", StringComparison.OrdinalIgnoreCase) || id.Any(IsHexLetter)
                        || (id.Length >= 3 && id[0] == '0' && id.All(char.IsDigit)))
                    {
                        idHex = true;
                    }
                    else if (id.All(char.IsDigit)
                             && (!long.TryParse(id, NumberStyles.HexNumber, CultureInfo.InvariantCulture, out var asHex) || asHex > MaxCanId))
                    {
                        idDecimal = true;
                    }
                }
            }

            foreach (var token in PayloadTokens(fields))
            {
                if (token.StartsWith("0x", StringComparison.OrdinalIgnoreCase) || token.Any(IsHexLetter))
                {
                    byteHex = true;
                }
                else if (token.Length >= 3 && token.All(char.IsDigit))
                {
                    byteDecimal = true;
                }
            }

            if (DataArrayIndex >= 0 && DataArrayIndex < fields.Count && Unquote(fields[DataArrayIndex]).StartsWith("["))
            {
                byteDecimal = true;
            }
        }

        if (idHex)
        {
            IdRadix = CsvRadix.Hex;
        }
        else if (idDecimal)
        {
            IdRadix = CsvRadix.Decimal;
        }

        if (byteHex)
        {
            ByteRadix = CsvRadix.Hex;
        }
        else if (byteDecimal)
        {
            ByteRadix = CsvRadix.Decimal;
        }
    }

    /// <summary>Parses one data row. False for the header, blank or malformed rows.</summary>
    public bool TryParse(string line, out ParsedCsvFrame frame)
    {
        frame = default;
        var fields = SplitFields(line);
        if (TimestampIndex >= fields.Count || IdIndex >= fields.Count)
        {
            return false;
        }

        if (!double.TryParse(Unquote(fields[TimestampIndex]), NumberStyles.Float, CultureInfo.InvariantCulture, out var timestamp))
        {
            return false;
        }

        if (!TryParseNumber(Unquote(fields[IdIndex]), IdRadix, MaxCanId, out var canId))
        {
            return false;
        }

        int? length = null;
        if (LengthIndex >= 0 && LengthIndex < fields.Count
            && int.TryParse(Unquote(fields[LengthIndex]), NumberStyles.Integer, CultureInfo.InvariantCulture, out var parsedLength)
            && parsedLength >= 0)
        {
            length = parsedLength;
        }

        var payload = new List<byte>(8);
        foreach (var token in PayloadTokens(fields))
        {
            if (length.HasValue && payload.Count >= length.Value)
            {
                break;
            }

            if (!TryParseNumber(token, ByteRadix, 0xFF, out var value))
            {
                return false; // malformed payload: skip the row rather than guess
            }

            payload.Add((byte)value);
        }

        int? channel = null;
        if (ChannelIndex >= 0 && ChannelIndex < fields.Count
            && int.TryParse(Unquote(fields[ChannelIndex]), NumberStyles.Integer, CultureInfo.InvariantCulture, out var parsedChannel))
        {
            channel = parsedChannel;
        }

        bool? extended = null;
        if (ExtendedIndex >= 0 && ExtendedIndex < fields.Count)
        {
            extended = Unquote(fields[ExtendedIndex]).ToLowerInvariant() switch
            {
                "1" or "true" or "yes" or "x" => true,
                "0" or "false" or "no" => false,
                _ => null,
            };
        }

        frame = new ParsedCsvFrame(timestamp, (int)canId, payload.ToArray(), channel, extended);
        return true;
    }

    public string Describe()
    {
        var payload = DataArrayIndex >= 0
            ? $"col {DataArrayIndex}"
            : $"cols {string.Join(",", ByteColumnIndexes)}";
        return $"{FormatName}: timestamp=col {TimestampIndex}, id=col {IdIndex} ({IdRadix}), "
             + $"channel={(ChannelIndex >= 0 ? $"col {ChannelIndex}" : "n/a")}, "
             + $"extended={(ExtendedIndex >= 0 ? $"col {ExtendedIndex}" : "n/a")}, "
             + $"length={(LengthIndex >= 0 ? $"col {LengthIndex}" : "n/a")}, payload={payload} ({ByteRadix})";
    }

    private IEnumerable<string> PayloadTokens(IReadOnlyList<string> fields)
    {
        if (DataArrayIndex >= 0)
        {
            if (DataArrayIndex >= fields.Count)
            {
                yield break;
            }

            var text = Unquote(fields[DataArrayIndex]).Trim('[', ']', '(', ')', '{', '}').Trim();
            var tokens = text.Split(new[] { ' ', '\t', ',', ';' }, StringSplitOptions.RemoveEmptyEntries);
            if (tokens.Length == 1 && tokens[0].Length > 2 && tokens[0].All(Uri.IsHexDigit) && ByteRadix == CsvRadix.Hex)
            {
                // contiguous hex string, e.g. "DEADBEEF"
                for (var i = 0; i + 1 < tokens[0].Length; i += 2)
                {
                    yield return tokens[0].Substring(i, 2);
                }

                yield break;
            }

            foreach (var token in tokens)
            {
                yield return token;
            }

            yield break;
        }

        foreach (var column in ByteColumnIndexes)
        {
            if (column >= fields.Count)
            {
                yield break;
            }

            var token = Unquote(fields[column]);
            if (token.Length == 0)
            {
                yield break; // trailing empty columns (SavvyCAN rows end with ",")
            }

            yield return token;
        }
    }

    private static bool TryParseNumber(string text, CsvRadix radix, long max, out long value)
    {
        value = 0;
        if (text.Length == 0)
        {
            return false;
        }

        bool ok;
        if (text.StartsWith("0x", StringComparison.OrdinalIgnoreCase))
        {
            ok = long.TryParse(text.Substring(2), NumberStyles.HexNumber, CultureInfo.InvariantCulture, out value);
        }
        else if (radix == CsvRadix.Hex)
        {
            ok = long.TryParse(text, NumberStyles.HexNumber, CultureInfo.InvariantCulture, out value);
        }
        else
        {
            ok = long.TryParse(text, NumberStyles.Integer, CultureInfo.InvariantCulture, out value);
        }

        return ok && value >= 0 && value <= max;
    }

    /// <summary>Splits on commas outside double quotes and [..] / (..) groups.</summary>
    internal static List<string> SplitFields(string line)
    {
        var fields = new List<string>();
        var current = new StringBuilder();
        var inQuotes = false;
        var depth = 0;
        foreach (var c in line)
        {
            switch (c)
            {
                case '"':
                    inQuotes = !inQuotes;
                    current.Append(c);
                    break;
                case '[' or '(' when !inQuotes:
                    depth++;
                    current.Append(c);
                    break;
                case ']' or ')' when !inQuotes:
                    depth = Math.Max(0, depth - 1);
                    current.Append(c);
                    break;
                case ',' when !inQuotes && depth == 0:
                    fields.Add(current.ToString());
                    current.Clear();
                    break;
                default:
                    current.Append(c);
                    break;
            }
        }

        fields.Add(current.ToString());
        return fields;
    }

    private static string Normalize(string header)
    {
        var name = Unquote(header);
        var dot = name.LastIndexOf('.');
        if (dot >= 0)
        {
            name = name.Substring(dot + 1); // "CAN_DataFrame.CAN_DataFrame.ID" -> "ID"
        }

        return new string(name.Where(char.IsLetterOrDigit).ToArray()).ToLowerInvariant();
    }

    private static int FindFirst(IReadOnlyList<string> names, IEnumerable<string> candidates)
    {
        foreach (var candidate in candidates)
        {
            for (var i = 0; i < names.Count; i++)
            {
                if (names[i] == candidate)
                {
                    return i;
                }
            }
        }

        return -1;
    }

    private static string Unquote(string value) => value.Trim().Trim('"').Trim();

    private static bool IsHexLetter(char c) => c is >= 'a' and <= 'f' or >= 'A' and <= 'F';
}

internal readonly struct ParsedCsvFrame
{
    public ParsedCsvFrame(double timestamp, int canId, byte[] payload, int? channel, bool? isExtended)
    {
        Timestamp = timestamp;
        CanId = canId;
        Payload = payload;
        Channel = channel;
        IsExtended = isExtended;
    }

    public double Timestamp { get; }
    public int CanId { get; }
    public byte[] Payload { get; }
    public int? Channel { get; }
    public bool? IsExtended { get; }
}
