using System.Globalization;
using System.IO;
using System.Text.RegularExpressions;
using CANvision.Native.Models;

namespace CANvision.Native.Services;

public sealed class CanLogImportService
{
    private static readonly Regex CandumpPattern = new(
        @"^\((?<ts>[-+]?\d+(?:\.\d+)?)\)\s+(?<iface>\S+)\s+(?<id>[0-9A-Fa-f]+)#(?<data>[0-9A-Fa-f]*)\s*$",
        RegexOptions.Compiled);

    private static readonly Regex CandumpNoParenPattern = new(
        @"^(?<ts>[-+]?\d+(?:\.\d+)?)\s+(?<iface>\S+)\s+(?<id>[0-9A-Fa-f]+)#(?<data>[0-9A-Fa-f]*)\s*$",
        RegexOptions.Compiled);

    private static readonly Regex AscPattern = new(
        @"^(?<ts>\d+(?:\.\d+)?)\s+(?<channel>\S+)\s+(?<id>[0-9A-Fa-f]+)\s+(?:Rx|Tx|rx|tx)\s+d\s+(?<dlc>\d+)\s+(?<payload>.+)$",
        RegexOptions.Compiled);

    private readonly AppLogger logger;
    private readonly PythonApiClient pythonApiClient;
    private readonly Dictionary<string, double> currentSignals = new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<string, DateTime> lastSignalTimestamps = new(StringComparer.OrdinalIgnoreCase);

    public CanLogImportService(AppLogger logger, PythonApiClient pythonApiClient)
    {
        this.logger = logger;
        this.pythonApiClient = pythonApiClient;
    }

    public async Task<CanImportResult> ParseFileAsync(string filePath, bool skipMlScoring = false, IProgress<double>? parseProgress = null, CancellationToken cancellationToken = default)
    {
        var frames = new List<CanFrame>();
        var packets = new List<PlaybackPacket>();
        var events = new List<CanPlaybackEvent>();
        var snapshots = new List<VehicleSnapshot>();
        var latestSignals = new Dictionary<string, DecodedSignal>(StringComparer.OrdinalIgnoreCase);

        var total = 0;
        var parsed = 0;
        var skipped = 0;
        var previousTimestamp = 0.0;
        var snapshot = VehicleSnapshot.Default();

        long fileSize = 0;
        try { fileSize = new FileInfo(filePath).Length; } catch { }
        var lastProgressTicks = DateTime.UtcNow.Ticks;

        using var reader = new StreamReader(filePath, System.Text.Encoding.UTF8, detectEncodingFromByteOrderMarks: true, bufferSize: 4096);
        string? rawLine;
        while ((rawLine = reader.ReadLine()) != null)
        {
            cancellationToken.ThrowIfCancellationRequested();
            total++;

            if (parseProgress != null && fileSize > 0)
            {
                var now = DateTime.UtcNow.Ticks;
                if (now - lastProgressTicks >= 1_000_000L) // 100 ms
                {
                    parseProgress.Report(reader.BaseStream.Position * 100.0 / fileSize);
                    lastProgressTicks = now;
                }
            }

            var line = rawLine;
            if (!TryParseFrame(line, out var frameRecord))
            {
                skipped++;
                continue;
            }

            parsed++;
            var frame = new CanFrame
            {
                TimestampUtc = BuildTimestamp(frameRecord.Timestamp),
                RelativeTimestampSeconds = frameRecord.Timestamp,
                CanId = frameRecord.CanId,
                Data = frameRecord.Bytes,
            };
            frames.Add(frame);

            var decodedSignals = DecodeFrame(frame);
            foreach (var signal in decodedSignals)
            {
                latestSignals[signal.Name] = signal;
                currentSignals[signal.FeatureKey] = signal.Value;
                lastSignalTimestamps[signal.FeatureKey] = signal.TimestampUtc;
            }

            snapshot = BuildSnapshot(latestSignals.Values, snapshot, frame);
            var anomalies = await BuildAnomaliesAsync(frame, decodedSignals, snapshot, skipMlScoring, cancellationToken).ConfigureAwait(false);

            var primaryText = decodedSignals.Count == 0
                ? $"{ResolveFrameName(frame.CanId)} 0x{frame.CanId:X3}"
                : string.Join(" | ", decodedSignals.Take(3).Select(s => $"{s.Name}={s.Value:F2}{s.Unit}"));

            var delay = previousTimestamp <= 0
                ? 0
                : Math.Max(1, (int)Math.Round((frameRecord.Timestamp - previousTimestamp) * 1000.0));
            previousTimestamp = frameRecord.Timestamp;

            packets.Add(new PlaybackPacket
            {
                Frame = frame,
                Signals = decodedSignals,
                Snapshot = snapshot,
                Anomalies = anomalies,
                EventText = primaryText,
                DelayMilliseconds = delay,
            });

            snapshots.Add(snapshot);
            events.Add(new CanPlaybackEvent(
                frame.TimestampUtc.ToLocalTime().ToString("HH:mm:ss.fff"),
                $"0x{frame.CanId:X3}",
                NormalizeHex(frameRecord.DataHex),
                primaryText));
        }

        parseProgress?.Report(100.0);
        logger.Info($"CAN import completed: file={Path.GetFileName(filePath)} total={total} parsed={parsed} skipped={skipped}");
        return new CanImportResult(frames, snapshots, events, packets, total, parsed, skipped);
    }

    private IReadOnlyList<DecodedSignal> DecodeFrame(CanFrame frame)
    {
        if (!PredefinedCanSchema.DbcMap.TryGetValue(frame.CanId, out var signalDefinitions))
        {
            return Array.Empty<DecodedSignal>();
        }

        var signals = new List<DecodedSignal>(signalDefinitions.Count);
        foreach (var definition in signalDefinitions)
        {
            var raw = ExtractRaw(frame.Data, definition);
            var value = (raw * definition.Factor) + definition.Offset;
            signals.Add(new DecodedSignal
            {
                Name = definition.Name,
                FeatureKey = string.IsNullOrWhiteSpace(definition.FeatureKey) ? definition.Name : definition.FeatureKey,
                Value = value,
                Unit = definition.Unit,
                TimestampUtc = frame.TimestampUtc,
                CanId = frame.CanId,
            });
        }

        return signals;
    }

    public async Task<ValidationScoreResponse?> ScoreValidationFileAsync(string filePath, CancellationToken cancellationToken)
    {
        return await pythonApiClient.ScoreValidationFileAsync(filePath, cancellationToken).ConfigureAwait(false);
    }

    private async Task<IReadOnlyList<CanAnomaly>> BuildAnomaliesAsync(
        CanFrame frame,
        IReadOnlyList<DecodedSignal> signals,
        VehicleSnapshot snapshot,
        bool skipMlScoring,
        CancellationToken cancellationToken)
    {
        var anomalies = new List<CanAnomaly>();

        foreach (var signal in signals)
        {
            if (TryBuildThresholdAnomaly(signal, out var anomaly))
            {
                anomalies.Add(anomaly);
            }
        }

        if (!skipMlScoring)
        {
            var mlAnomaly = await BuildMlAnomalyAsync(frame, snapshot, cancellationToken).ConfigureAwait(false);
            if (mlAnomaly is not null)
            {
                anomalies.Add(mlAnomaly);
            }
        }

        return anomalies;
    }

    private async Task<CanAnomaly?> BuildMlAnomalyAsync(CanFrame frame, VehicleSnapshot snapshot, CancellationToken cancellationToken)
    {
        var payload = frame.Data ?? Array.Empty<byte>();
        var mlResult = await pythonApiClient.InferFrameAsync(
            frame.RelativeTimestampSeconds,
            frame.CanId,
            payload,
            snapshot.Source,
            cancellationToken).ConfigureAwait(false);
        if (mlResult is null || string.Equals(mlResult.Label, "normal", StringComparison.OrdinalIgnoreCase))
        {
            return null;
        }

        var severity = Math.Max(0, Math.Min(100, mlResult.SeverityScore));
        return new CanAnomaly
        {
            Code = "AI-001",
            Title = "AI ANOMALY",
            Description = $"ML detected {mlResult.Label} behavior with score {mlResult.Score:F3}.",
            Severity = severity >= 80 ? "CRITICAL" : (severity >= 40 ? "WARNING" : "INFO"),
            SeverityScore = severity,
            AnomalyScore = mlResult.Score,
            RelatedCanId = frame.CanId,
            TimestampUtc = snapshot.UpdatedAt,
            Source = "ai",
        };
    }

    private static bool TryBuildThresholdAnomaly(DecodedSignal signal, out CanAnomaly anomaly)
    {
        anomaly = null!;
        if (signal.FeatureKey == "Temp" && signal.Value >= 85)
        {
            anomaly = NewAnomaly("THM-102", "OVERHEAT CRITICAL", "Battery temperature exceeded safe range.", 92, signal);
            return true;
        }

        if (signal.FeatureKey == "Voltage" && signal.Value < 290)
        {
            anomaly = NewAnomaly("VLT-301", "UNDER VOLTAGE", "Battery pack voltage dropped below threshold.", 64, signal);
            return true;
        }

        if ((signal.FeatureKey == "Current" || signal.FeatureKey == "PeakAmperage") && Math.Abs(signal.Value) >= 550)
        {
            anomaly = NewAnomaly("PWR-220", "OVER CURRENT", "Current draw exceeded configured threshold.", 71, signal);
            return true;
        }

        if (signal.FeatureKey == "RPM" && signal.Value >= 9500)
        {
            anomaly = NewAnomaly("MTR-043", "MOTOR OVERSPEED", "Motor RPM exceeded nominal operating envelope.", 58, signal);
            return true;
        }

        return false;
    }

    private static CanAnomaly NewAnomaly(string code, string title, string description, double severity, DecodedSignal signal)
    {
        return new CanAnomaly
        {
            Code = code,
            Title = title,
            Description = description,
            Severity = severity >= 80 ? "CRITICAL" : "WARNING",
            SeverityScore = severity,
            AnomalyScore = severity / 100.0,
            RelatedCanId = signal.CanId,
            TimestampUtc = signal.TimestampUtc,
            Source = "signal",
        };
    }

    private VehicleSnapshot BuildSnapshot(IEnumerable<DecodedSignal> signals, VehicleSnapshot previous, CanFrame frame)
    {
        var next = CloneSnapshot(previous);
        next.Source = "log-playback";
        next.UpdatedAt = frame.TimestampUtc;

        foreach (var signal in signals)
        {
            switch (signal.FeatureKey)
            {
                case "Battery_SOC":
                    next.SOC = signal.Value;
                    next.Battery = (int)Math.Round(signal.Value);
                    break;
                case "Voltage":
                    next.BatteryVoltage = signal.Value;
                    break;
                case "Current":
                    next.BatteryCurrent = signal.Value;
                    break;
                case "Temp":
                    next.BatteryTemp = signal.Value;
                    next.Temperature = (int)Math.Round(signal.Value);
                    break;
                case "Speed":
                    next.VehicleSpeed = signal.Value;
                    break;
                case "RPM":
                    next.MotorRPM = (int)Math.Round(signal.Value);
                    break;
                case "MotorTemp":
                    next.MotorTemp = signal.Value;
                    break;
                case "InverterTemp":
                    next.InverterTemp = signal.Value;
                    break;
                case "PeakAmperage":
                    next.PeakAmperage = signal.Value;
                    break;
                case "FaultFlags":
                    var flags = (int)Math.Round(signal.Value);
                    next.BMSFault = (flags & 0x1) != 0;
                    next.MotorFault = (flags & 0x2) != 0;
                    next.OverheatFault = (flags & 0x4) != 0 || next.BatteryTemp >= 85 || next.MotorTemp >= 95;
                    next.OverCurrentFault = (flags & 0x8) != 0 || Math.Abs(next.BatteryCurrent) >= 550 || next.PeakAmperage >= 550;
                    next.UnderVoltageFault = (flags & 0x10) != 0 || (next.BatteryVoltage > 0 && next.BatteryVoltage < 290);
                    break;
            }
        }

        next.BatteryPower = next.BatteryVoltage * next.BatteryCurrent / 1000.0;
        next.MotorStatus = (next.BMSFault || next.MotorFault || next.OverheatFault || next.OverCurrentFault || next.UnderVoltageFault)
            ? "DEGRADED"
            : "OK";
        next.PerformanceScore = Math.Max(0, Math.Min(100, 100 - (Math.Abs(next.BatteryCurrent) / 20.0) - Math.Max(0, next.BatteryTemp - 45)));
        next.Frequency = EstimateFrequency(frame.TimestampUtc);
        next.TimeDiff = EstimateTimeDiff(frame.TimestampUtc);
        return next;
    }

    private static VehicleSnapshot CloneSnapshot(VehicleSnapshot snapshot)
    {
        return new VehicleSnapshot
        {
            Battery = snapshot.Battery,
            Temperature = snapshot.Temperature,
            MotorStatus = snapshot.MotorStatus,
            Source = snapshot.Source,
            UpdatedAt = snapshot.UpdatedAt,
            SOC = snapshot.SOC,
            SOH = snapshot.SOH,
            BatteryVoltage = snapshot.BatteryVoltage,
            BatteryCurrent = snapshot.BatteryCurrent,
            BatteryPower = snapshot.BatteryPower,
            BatteryTemp = snapshot.BatteryTemp,
            VehicleSpeed = snapshot.VehicleSpeed,
            MotorTemp = snapshot.MotorTemp,
            MotorRPM = snapshot.MotorRPM,
            InverterTemp = snapshot.InverterTemp,
            DriveMode = snapshot.DriveMode,
            Gear = snapshot.Gear,
            OverheatFault = snapshot.OverheatFault,
            OverCurrentFault = snapshot.OverCurrentFault,
            UnderVoltageFault = snapshot.UnderVoltageFault,
            BMSFault = snapshot.BMSFault,
            MotorFault = snapshot.MotorFault,
            PerformanceScore = snapshot.PerformanceScore,
            Frequency = snapshot.Frequency,
            TimeDiff = snapshot.TimeDiff,
            PeakAmperage = snapshot.PeakAmperage,
        };
    }

    private DateTime BuildTimestamp(double seconds)
    {
        var baseTime = DateTime.UtcNow.Date;
        return baseTime.AddSeconds(seconds);
    }

    private double EstimateFrequency(DateTime timestampUtc)
    {
        const string key = "__frame__";
        if (!lastSignalTimestamps.TryGetValue(key, out var previous))
        {
            lastSignalTimestamps[key] = timestampUtc;
            return 0;
        }

        var delta = (timestampUtc - previous).TotalSeconds;
        lastSignalTimestamps[key] = timestampUtc;
        return delta <= 0 ? 0 : 1.0 / delta;
    }

    private double EstimateTimeDiff(DateTime timestampUtc)
    {
        const string key = "__timediff__";
        if (!lastSignalTimestamps.TryGetValue(key, out var previous))
        {
            lastSignalTimestamps[key] = timestampUtc;
            return 0;
        }

        var delta = (timestampUtc - previous).TotalSeconds;
        lastSignalTimestamps[key] = timestampUtc;
        return Math.Max(0, delta);
    }

    private static double ExtractRaw(byte[] data, SignalDefinition definition)
    {
        ulong raw = 0;
        if (definition.IsLittleEndian)
        {
            for (var i = 0; i < data.Length; i++)
            {
                raw |= ((ulong)data[i]) << (8 * i);
            }
        }
        else
        {
            for (var i = 0; i < data.Length; i++)
            {
                raw = (raw << 8) | data[i];
            }
        }

        var mask = definition.Length >= 64 ? ulong.MaxValue : ((1UL << definition.Length) - 1UL);
        raw = (raw >> definition.StartBit) & mask;

        if (!definition.IsSigned)
        {
            return raw;
        }

        var signBit = 1UL << (definition.Length - 1);
        if ((raw & signBit) == 0)
        {
            return raw;
        }

        var signed = (long)(raw | (~mask));
        return signed;
    }

    private string ResolveFrameName(int canId)
    {
        return PredefinedCanSchema.TranslationMap.TryGetValue(canId, out var name) ? name : $"CAN_{canId:X3}";
    }

    private static bool TryParseFrame(string rawLine, out CanFrameRecord frame)
    {
        frame = default;
        if (string.IsNullOrWhiteSpace(rawLine))
        {
            return false;
        }

        var line = rawLine.Trim();
        if (line.StartsWith("#") || line.StartsWith("//") || line.StartsWith(";"))
        {
            return false;
        }

        if (TryParseCandump(line, out frame))
        {
            return true;
        }

        if (TryParseAsc(line, out frame))
        {
            return true;
        }

        if (TryParseCsv(line, out frame))
        {
            return true;
        }

        return false;
    }

    private static bool TryParseCandump(string line, out CanFrameRecord frame)
    {
        frame = default;
        var match = CandumpPattern.Match(line);
        if (!match.Success)
        {
            match = CandumpNoParenPattern.Match(line);
        }

        if (!match.Success ||
            !double.TryParse(match.Groups["ts"].Value, NumberStyles.Float, CultureInfo.InvariantCulture, out var ts) ||
            !int.TryParse(match.Groups["id"].Value, NumberStyles.HexNumber, CultureInfo.InvariantCulture, out var canId))
        {
            return false;
        }

        var bytes = ParseBytes(match.Groups["data"].Value);
        frame = new CanFrameRecord(ts, canId, bytes, NormalizeHex(match.Groups["data"].Value));
        return true;
    }

    private static bool TryParseAsc(string line, out CanFrameRecord frame)
    {
        frame = default;
        var match = AscPattern.Match(line);
        if (!match.Success ||
            !double.TryParse(match.Groups["ts"].Value, NumberStyles.Float, CultureInfo.InvariantCulture, out var ts) ||
            !int.TryParse(match.Groups["id"].Value, NumberStyles.HexNumber, CultureInfo.InvariantCulture, out var canId) ||
            !int.TryParse(match.Groups["dlc"].Value, out var dlc))
        {
            return false;
        }

        var payloadTokens = match.Groups["payload"].Value.Split(new[] { ' ', '\t' }, StringSplitOptions.RemoveEmptyEntries);
        var hex = string.Concat(payloadTokens.Take(Math.Max(0, Math.Min(dlc, payloadTokens.Length))).Select(p => p.PadLeft(2, '0')));
        var bytes = ParseBytes(hex);
        frame = new CanFrameRecord(ts, canId, bytes, NormalizeHex(hex));
        return true;
    }

    private static bool TryParseCsv(string line, out CanFrameRecord frame)
    {
        frame = default;
        var parts = line.Split(',');
        if (parts.Length < 3)
            return false;

        if (!double.TryParse(parts[0].Trim(), NumberStyles.Float, CultureInfo.InvariantCulture, out var ts))
            return false;

        var canText = parts[1].Trim();
        if (canText.StartsWith("0x", StringComparison.OrdinalIgnoreCase))
            canText = canText.Substring(2);
        if (!int.TryParse(canText, NumberStyles.HexNumber, CultureInfo.InvariantCulture, out var canId))
            return false;

        // SavvyCAN format: Time Stamp, ID, Extended(false/true), Dir(Rx/Tx), Bus, LEN, D1..D8
        if (parts.Length >= 7)
        {
            var p2 = parts[2].Trim();
            var p3 = parts[3].Trim();
            if ((p2.Equals("false", StringComparison.OrdinalIgnoreCase) || p2.Equals("true", StringComparison.OrdinalIgnoreCase)) &&
                (p3.Equals("Rx", StringComparison.OrdinalIgnoreCase) || p3.Equals("Tx", StringComparison.OrdinalIgnoreCase)))
            {
                var dataBytes = new byte[8];
                var dlc = 0;
                if (int.TryParse(parts[5].Trim(), NumberStyles.Integer, CultureInfo.InvariantCulture, out var d))
                    dlc = Math.Min(8, d);
                for (var i = 0; i < dlc && i + 6 < parts.Length; i++)
                {
                    if (byte.TryParse(parts[i + 6].Trim(), NumberStyles.HexNumber, CultureInfo.InvariantCulture, out var b))
                        dataBytes[i] = b;
                }
                var savvyHex = BitConverter.ToString(dataBytes, 0, dlc).Replace("-", string.Empty);
                frame = new CanFrameRecord(ts, canId, dataBytes, savvyHex);
                return true;
            }
        }

        // Generic format: timestamp, can_id, hex_data columns (concatenated)
        var dataHex = string.Concat(parts.Skip(2)).Replace(" ", string.Empty);
        var bytes = ParseBytes(dataHex);
        frame = new CanFrameRecord(ts, canId, bytes, NormalizeHex(dataHex));
        return true;
    }

    private static byte[] ParseBytes(string hex)
    {
        var normalized = NormalizeHex(hex);
        var output = new byte[8];
        for (var i = 0; i < Math.Min(8, normalized.Length / 2); i++)
        {
            var slice = normalized.Substring(i * 2, 2);
            if (byte.TryParse(slice, NumberStyles.HexNumber, CultureInfo.InvariantCulture, out var b))
            {
                output[i] = b;
            }
        }

        return output;
    }

    private static string NormalizeHex(string value)
    {
        var text = value?.Trim() ?? string.Empty;
        text = new string(text.Where(Uri.IsHexDigit).ToArray());
        if (text.Length % 2 == 1)
        {
            text = "0" + text;
        }

        return text.ToUpperInvariant();
    }

    private readonly struct CanFrameRecord
    {
        public CanFrameRecord(double timestamp, int canId, byte[] bytes, string dataHex)
        {
            Timestamp = timestamp;
            CanId = canId;
            Bytes = bytes;
            DataHex = dataHex;
        }

        public double Timestamp { get; }
        public int CanId { get; }
        public byte[] Bytes { get; }
        public string DataHex { get; }
    }
}

public sealed class CanImportResult
{
    public CanImportResult(
        IReadOnlyList<CanFrame> frames,
        IReadOnlyList<VehicleSnapshot> snapshots,
        IReadOnlyList<CanPlaybackEvent> events,
        IReadOnlyList<PlaybackPacket> packets,
        int totalLines,
        int parsedLines,
        int skippedLines)
    {
        Frames = frames;
        Snapshots = snapshots;
        Events = events;
        Packets = packets;
        TotalLines = totalLines;
        ParsedLines = parsedLines;
        SkippedLines = skippedLines;
    }

    public IReadOnlyList<CanFrame> Frames { get; }
    public IReadOnlyList<VehicleSnapshot> Snapshots { get; }
    public IReadOnlyList<CanPlaybackEvent> Events { get; }
    public IReadOnlyList<PlaybackPacket> Packets { get; }
    public int TotalLines { get; }
    public int ParsedLines { get; }
    public int SkippedLines { get; }
}

public sealed class CanPlaybackEvent
{
    public CanPlaybackEvent(string timestamp, string frameId, string dataHex, string decodedSignal)
    {
        Timestamp = timestamp;
        FrameId = frameId;
        DataHex = dataHex;
        DecodedSignal = decodedSignal;
    }

    public string Timestamp { get; }
    public string FrameId { get; }
    public string DataHex { get; }
    public string DecodedSignal { get; }
}
