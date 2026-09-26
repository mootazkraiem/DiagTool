using System.Globalization;
using System.IO;
using CANvision.Native.Services;
using Xunit;

namespace CANvision.Native.Tests;

/// <summary>
/// Importer regression tests against the real logs shipped in the repository.
/// Expected values are read independently from the raw files where possible,
/// so the tests check the importer against the source data rather than against
/// its own output.
/// </summary>
public sealed class CanLogImportTests
{
    private static readonly string Root = FindRepoRoot();

    private static string Asset(params string[] parts) => Path.Combine(new[] { Root }.Concat(parts).ToArray());

    private static CanLogImportService NewService()
    {
        var logger = new AppLogger();
        return new CanLogImportService(logger, new PythonApiClient(logger));
    }

    private static Task<CanImportResult> Import(string path) =>
        NewService().ParseFileAsync(path, skipMlScoring: true);

    // ── asammdf / CSS Electronics MF4 export (file_16.csv) ───────────────────

    [Fact]
    public async Task Mf4Export_UsesIdColumn_NotBusChannel()
    {
        var result = await Import(Asset("assets", "Skoda Enyaq", "file_16.csv"));

        Assert.Equal(19340, result.TotalLines);
        Assert.Equal(19339, result.ParsedLines);
        Assert.Equal(1, result.SkippedLines); // the header row

        // Before the fix every frame came out as 0x001 (the BusChannel column).
        Assert.DoesNotContain(result.Frames, f => f.CanId == 1);

        var expected = new Dictionary<int, int>
        {
            [402522235] = 4178,
            [402391163] = 3798,
            [2001] = 3779,
            [1862] = 1516,
            [1968] = 1516,
            [1895] = 1516,
            [402391225] = 760,
            [402522297] = 760,
            [402391158] = 758,
            [402522230] = 758,
        };
        var actual = result.Frames.GroupBy(f => f.CanId).ToDictionary(g => g.Key, g => g.Count());
        Assert.Equal(expected.OrderBy(kv => kv.Key), actual.OrderBy(kv => kv.Key));
    }

    [Fact]
    public async Task Mf4Export_IdsMatchRawIdColumn_RowByRow()
    {
        var path = Asset("assets", "Skoda Enyaq", "file_16.csv");
        var raw = ReadRawColumns(path, ".ID");
        var result = await Import(path);

        Assert.Equal(raw.Count, result.Frames.Count);
        for (var i = 0; i < raw.Count; i++)
        {
            Assert.Equal(int.Parse(raw[i], CultureInfo.InvariantCulture), result.Frames[i].CanId);
        }
    }

    [Fact]
    public async Task Mf4Export_PayloadComesFromDataBytesColumn_RowByRow()
    {
        var path = Asset("assets", "Skoda Enyaq", "file_16.csv");
        var raw = ReadRawColumns(path, ".DataBytes");
        var result = await Import(path);

        Assert.Equal(raw.Count, result.Frames.Count);
        for (var i = 0; i < raw.Count; i++)
        {
            // "[  5  98  70  91   2  22 170 170]" -> decimal byte list
            var expected = raw[i].Trim('[', ']')
                .Split(new[] { ' ' }, StringSplitOptions.RemoveEmptyEntries)
                .Select(t => byte.Parse(t, CultureInfo.InvariantCulture))
                .ToArray();
            Assert.Equal(expected, result.Frames[i].Data.Take(expected.Length).ToArray());
        }

        // Spot check the first two rows literally.
        Assert.Equal(new byte[] { 3, 34, 70, 91, 85, 85, 85, 85 }, result.Frames[0].Data);
        Assert.Equal(402391225, result.Frames[0].CanId);
        Assert.Equal(new byte[] { 5, 98, 70, 91, 2, 22, 170, 170 }, result.Frames[1].Data);
        Assert.Equal(402522297, result.Frames[1].CanId);
    }

    [Fact]
    public async Task Mf4Export_ExtractsChannelExtendedFlagAndTimestamp()
    {
        var path = Asset("assets", "Skoda Enyaq", "file_16.csv");
        var channels = ReadRawColumns(path, ".BusChannel");
        var ide = ReadRawColumns(path, ".IDE");
        var stamps = ReadRawColumns(path, "timestamps");
        var result = await Import(path);

        for (var i = 0; i < result.Frames.Count; i++)
        {
            var frame = result.Frames[i];
            Assert.Equal(int.Parse(channels[i], CultureInfo.InvariantCulture), frame.Channel);
            Assert.Equal(ide[i] == "1", frame.IsExtended);
            Assert.Equal(double.Parse(stamps[i], CultureInfo.InvariantCulture), frame.RelativeTimestampSeconds, 9);
        }

        // 29-bit identifiers carry IDE=1, 11-bit ones IDE=0.
        Assert.All(result.Frames, f => Assert.Equal(f.CanId > 0x7FF, f.IsExtended));
    }

    [Fact]
    public async Task Mf4Export_PacketEventsCarryRealIds()
    {
        var result = await Import(Asset("assets", "Skoda Enyaq", "file_16.csv"));

        Assert.DoesNotContain(result.Packets, p => p.EventText.StartsWith("CAN_001", StringComparison.Ordinal));
        Assert.Equal(10, result.Events.Select(e => e.FrameId).Distinct().Count());
        Assert.Equal($"0x{402391225:X3}", result.Events[0].FrameId);
        Assert.Equal("032246", result.Events[0].DataHex.Substring(0, 6));
    }

    // ── SavvyCAN exports (previously working; must stay identical) ───────────

    [Fact]
    public async Task SavvyCan_HexIdsAndBytes_RowByRow()
    {
        var path = Asset("assets", "EV-CANlogs-main", "BYD Atto 3", "CAN run 15sec with 12D-50ms & 441-100ms.csv");
        var result = await Import(path);
        var rows = File.ReadAllLines(path).Skip(1).Where(l => l.Trim().Length > 0).ToList();

        Assert.Equal(rows.Count, result.Frames.Count);
        for (var i = 0; i < rows.Count; i++)
        {
            var f = rows[i].Split(',');
            Assert.Equal(Convert.ToInt32(f[1], 16), result.Frames[i].CanId);
            var len = int.Parse(f[5], CultureInfo.InvariantCulture);
            var expected = Enumerable.Range(0, len).Select(k => Convert.ToByte(f[6 + k], 16)).ToArray();
            Assert.Equal(expected, result.Frames[i].Data.Take(len).ToArray());
            Assert.Equal(int.Parse(f[4], CultureInfo.InvariantCulture), result.Frames[i].Channel);
            Assert.False(result.Frames[i].IsExtended);
        }
    }

    [Fact]
    public async Task SavvyCan_WithoutDirColumn_ParsesHexBytes()
    {
        // "Time Stamp,ID,Extended,Bus,LEN,D1..D8" with single-digit hex bytes.
        // The old positional path concatenated every column into the payload here.
        var result = await Import(Asset("assets", "EV-CANlogs-main", "Mitshubishi Outlander", "outlander-2016-heater.csv"));

        Assert.Equal(0x75A, result.Frames[0].CanId);
        Assert.Equal(new byte[] { 0x03, 0xE8, 0x03, 0xE8, 0x64, 0x64, 0x38, 0x39 }, result.Frames[0].Data);
        Assert.Equal(0x56B, result.Frames[1].CanId);
        Assert.Equal(new byte[] { 0xAA, 0x02, 0x00, 0x00, 0x80, 0xAA, 0x00, 0x00 }, result.Frames[1].Data);
    }

    [Fact]
    public async Task SavvyCan_TimeStampMicroseconds_BecomeSeconds()
    {
        // SavvyCAN "Time Stamp" is microseconds; the backend (csv_frames.py) and the
        // training loader read it as such. First rows: 12720014, 12720634, 12720651.
        var result = await Import(Asset("assets", "EV-CANlogs-main", "Jaguar IPACE", "canbus_turning_on.csv"));

        Assert.Equal(12.720014, result.Frames[0].RelativeTimestampSeconds, 9);
        Assert.Equal(0.000620, result.Frames[1].RelativeTimestampSeconds - result.Frames[0].RelativeTimestampSeconds, 9);
        Assert.Equal(0.000017, result.Frames[2].RelativeTimestampSeconds - result.Frames[1].RelativeTimestampSeconds, 9);
    }

    [Fact]
    public void SavvyCan_Layout_DividesOnlySavvyCanTimeStamp()
    {
        Assert.Equal(1_000_000.0, CsvCanLayout.FromHeader("Time Stamp,ID,Extended,Dir,Bus,LEN,D1,D2")!.TimestampDivisor);
        Assert.Equal(1.0, CsvCanLayout.FromHeader("timestamp,can_id,b0,b1,b2,b3,b4,b5,b6,b7")!.TimestampDivisor);
    }

    // ── CANvision converter / simulator CSV (timestamp,can_id,b0..b7) ───────

    [Fact]
    public async Task ReplayCsv_KeepsHexIdSemantics_BytesDecimalByEvidence()
    {
        // No hex evidence in "260,316,329,545": the previous (and backend) hex
        // reading is kept. Byte columns contain "128", so bytes are decimal; the old
        // positional path concatenated every column into the payload instead.
        var result = await Import(Asset("backend", "ml", "outputs", "replay_logs", "normal.csv"));

        Assert.Equal(new[] { 0x260, 0x316, 0x329, 0x545 }, result.Frames.Select(f => f.CanId).Distinct().OrderBy(x => x).ToArray());
        Assert.Equal(new byte[] { 0, 128, 0, 51, 0, 80, 5, 0 }, result.Frames[0].Data);
    }

    [Fact]
    public async Task SessionCsv_KeepsHexIdSemantics_BytesDecimalByEvidence()
    {
        var result = await Import(Asset("backend", "ml", "outputs", "sessions", "session_2026-06-20_16-54-47.csv"));

        Assert.Equal(0x1009, result.Frames[0].CanId);
        Assert.Equal(new byte[] { 12, 28, 87, 240, 0, 0, 0, 0 }, result.Frames[0].Data);
    }

    // ── non-header formats: the untouched per-line parsers ───────────────────

    [Fact]
    public async Task Candump_Unchanged()
    {
        var result = await Import(Asset("assets", "data", "Prototype", "dosattack.log"));

        Assert.Equal(0x1A0, result.Frames[0].CanId);
        Assert.Equal(new byte[] { 0, 0, 0, 0, 0, 0, 0, 0x69 }, result.Frames[0].Data);
        Assert.Null(result.Frames[0].Channel);
    }

    [Fact]
    public async Task HeaderlessGenericCsv_Unchanged()
    {
        var path = TempFile("0.100,1A0,DEADBEEF01020304\n0.200,7DF,0201\n");
        var result = await Import(path);

        Assert.Equal(2, result.ParsedLines);
        Assert.Equal(0x1A0, result.Frames[0].CanId);
        Assert.Equal(new byte[] { 0xDE, 0xAD, 0xBE, 0xEF, 1, 2, 3, 4 }, result.Frames[0].Data);
        Assert.Equal(0x7DF, result.Frames[1].CanId);
    }

    [Fact]
    public async Task Asc_Unchanged()
    {
        var path = TempFile("0.001000 1 316 Rx d 8 DE AD BE EF 01 02 03 04\n0.002000 1 329 Tx d 4 FF 00 11 22\n");
        var result = await Import(path);

        Assert.Equal(0x316, result.Frames[0].CanId);
        Assert.Equal(new byte[] { 0xDE, 0xAD, 0xBE, 0xEF, 1, 2, 3, 4 }, result.Frames[0].Data);
        Assert.Equal(0x329, result.Frames[1].CanId);
    }

    // ── layout detection rules ───────────────────────────────────────────────

    [Fact]
    public void Layout_NotDetectedForHeaderlessOrLineFormats()
    {
        Assert.Null(CsvCanLayout.FromHeader("0.100,1A0,DEADBEEF"));
        Assert.Null(CsvCanLayout.FromHeader("(1531471699.132994) can0 1A0#0000000000000069"));
        Assert.Null(CsvCanLayout.Detect(Asset("assets", "data", "Prototype", "dosattack.log")));
    }

    [Theory]
    [InlineData("Time Stamp,ID,Extended,Dir,Bus,LEN,D1,D2", "1,0000012D,false,Rx,0,2,A0,28", "Hex", "Hex")]
    [InlineData("timestamps,CAN_DataFrame.CAN_DataFrame.BusChannel,CAN_DataFrame.CAN_DataFrame.ID,CAN_DataFrame.CAN_DataFrame.DataBytes",
                "0.0,1,402391225,[ 3 34 70 91]", "Decimal", "Decimal")]
    [InlineData("timestamp,can_id,b0,b1", "0.1,260,0,128", "Hex", "Decimal")]
    [InlineData("timestamp,can_id,b0,b1", "0.1,7DF,02,1F", "Hex", "Hex")]
    [InlineData("timestamp,can_id,b0,b1", "0.1,402391225,1,2", "Decimal", "Hex")]
    public void Layout_RadixFollowsEvidence(string header, string row, string expectedIdRadix, string expectedByteRadix)
    {
        // CsvRadix is internal, so the expectation is passed by name.
        var idRadix = (CsvRadix)Enum.Parse(typeof(CsvRadix), expectedIdRadix);
        var byteRadix = (CsvRadix)Enum.Parse(typeof(CsvRadix), expectedByteRadix);
        var layout = CsvCanLayout.FromHeader(header);
        Assert.NotNull(layout);
        layout!.DecideRadix(new[] { CsvCanLayout.SplitFields(row) });

        Assert.Equal(idRadix, layout.IdRadix);
        Assert.Equal(byteRadix, layout.ByteRadix);
    }

    [Fact]
    public void Layout_Mf4Export_MapsColumnsByName()
    {
        var header = File.ReadLines(Asset("assets", "Skoda Enyaq", "file_16.csv")).First();
        var layout = CsvCanLayout.FromHeader(header)!;

        Assert.Equal("asammdf-mf4-export", layout.FormatName);
        Assert.Equal(0, layout.TimestampIndex);
        Assert.Equal(1, layout.ChannelIndex);
        Assert.Equal(2, layout.IdIndex);
        Assert.Equal(3, layout.ExtendedIndex);
        Assert.Equal(6, layout.DataArrayIndex);
    }

    // ── helpers ──────────────────────────────────────────────────────────────

    /// <summary>Reads one column of every data row by header-name suffix, independently of the importer.</summary>
    private static List<string> ReadRawColumns(string path, string headerSuffix)
    {
        var lines = File.ReadAllLines(path);
        var header = lines[0].Split(',');
        var column = Array.FindIndex(header, h => h.EndsWith(headerSuffix, StringComparison.Ordinal));
        Assert.True(column >= 0, $"column *{headerSuffix} not found");

        // DataBytes cells contain no commas in this export ("[ 3 34 70 ...]").
        return lines.Skip(1).Where(l => l.Trim().Length > 0).Select(l => l.Split(',')[column].Trim()).ToList();
    }

    private static string TempFile(string content)
    {
        var path = Path.Combine(Path.GetTempPath(), $"cv_import_{Guid.NewGuid():N}.log");
        File.WriteAllText(path, content);
        return path;
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
