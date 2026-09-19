using System.IO;
using CANvision.Native.Models;
using CANvision.Native.Services;
using CANvision.Native.ViewModels;
using Newtonsoft.Json;
using Xunit;

namespace CANvision.Native.Tests;

/// <summary>
/// Offline import turns the backend's /analyze detections into the alert history
/// that Anomaly Intel, Diagnostics and the Log Playback lanes read. The detections
/// below are copied from a real /analyze response for the first 5,000 rows of
/// assets/Skoda Enyaq/file_13.csv (General Model).
/// </summary>
public sealed class OfflineAlertTests
{
    private const string RealResponse = @"{ ""anomalies"": [
      {""context"": {""timestamp"": 0.0, ""can_id"": ""0x17FC00B9"", ""anomaly_score"": 0.9958122951626834, ""detection_layers"": [""ML""], ""top_feature"": ""msg_rate"", ""timing_score"": 0.0, ""temporal_score"": 0.0, ""plausibility_checked"": false, ""plausibility_passed"": true}, ""explanation"": {""kb_match_label"": """"}},
      {""context"": {""timestamp"": 0.3500000000000001, ""can_id"": ""0x17FC007B"", ""anomaly_score"": 1.0, ""detection_layers"": [""ML""], ""top_feature"": ""msg_rate"", ""timing_score"": 0.0, ""temporal_score"": 0.0, ""plausibility_checked"": false, ""plausibility_passed"": true}, ""explanation"": {""kb_match_label"": ""dos_burst""}},
      {""context"": {""timestamp"": 2.20005, ""can_id"": ""0x17FC0076"", ""anomaly_score"": 0.998603153833205, ""detection_layers"": [""ML""], ""top_feature"": ""msg_rate"", ""timing_score"": 0.0, ""temporal_score"": 0.0, ""plausibility_checked"": false, ""plausibility_passed"": true}, ""explanation"": {""kb_match_label"": ""ML Isolation Outlier""}},
      {""context"": {""timestamp"": 2.4017, ""can_id"": ""0x7B0"", ""anomaly_score"": 1.0, ""detection_layers"": [""ML"", ""PLAUSIBILITY"", ""TEMPORAL""], ""top_feature"": ""msg_rate"", ""timing_score"": 0.0, ""temporal_score"": 1.0, ""plausibility_checked"": true, ""plausibility_passed"": false}, ""explanation"": {""kb_match_label"": ""DoS / Flood Attack""}}
    ] }";

    private static async Task<IReadOnlyList<PlaybackPacket>> ImportFile13()
    {
        var logger = new AppLogger();
        var service = new CanLogImportService(logger, new PythonApiClient(logger));
        var result = await service.ParseFileAsync(Path.Combine(FindRepoRoot(), "assets", "Skoda Enyaq", "file_13.csv"), skipMlScoring: true);
        return result.Packets.ToList();
    }

    private static List<HomeViewModel.ApiDetection> Convert(IReadOnlyList<PlaybackPacket> packets) =>
        HomeViewModel.ConvertApiAnomalies(JsonConvert.DeserializeObject<PythonAnalyzeResponse>(RealResponse), packets);

    [Fact]
    public async Task Every_detection_becomes_an_alert_at_its_own_frame_time()
    {
        var packets = await ImportFile13();
        var alerts = Convert(packets).Select(d => d.Alert).ToList();

        Assert.Equal(4, alerts.Count);
        var expected = new[] { 0.0, 0.3500000000000001, 2.20005, 2.4017 };
        for (var i = 0; i < expected.Length; i++)
            Assert.Equal(expected[i], alerts[i].RelativeSeconds, 9);

        // Each alert carries the wall-clock time of the frame it flags, not the import time.
        foreach (var alert in alerts)
        {
            var frame = packets.OrderBy(p => Math.Abs(p.Frame.RelativeTimestampSeconds - alert.RelativeSeconds)).First().Frame;
            Assert.Equal(alert.RelativeSeconds, frame.RelativeTimestampSeconds, 9);
            Assert.Equal(frame.TimestampUtc, alert.TimestampUtc);
        }
        Assert.Equal(4, alerts.Select(a => a.TimestampUtc).Distinct().Count());
    }

    [Fact]
    public async Task Attack_type_comes_from_the_knowledge_base_label_then_the_detection_layer()
    {
        var alerts = Convert(await ImportFile13()).Select(d => d.Alert).ToList();

        Assert.Equal(new[] { "ML", "DOS_BURST", "ML ISOLATION OUTLIER", "DOS / FLOOD ATTACK" }, alerts.Select(a => a.AttackType));
        Assert.Equal(new[] { "0x17FC00B9", "0x17FC007B", "0x17FC0076", "0x7B0" }, alerts.Select(a => a.CanId));
    }

    [Fact]
    public async Task Reason_carries_the_layer_scores_the_intel_breakdown_reads()
    {
        var alerts = Convert(await ImportFile13()).Select(d => d.Alert).ToList();

        Assert.Equal("Layers: ML · top feature msg_rate, timing=0.000, payload=0.000, ml=0.996, persistence=0.000", alerts[0].Reason);
        // Failed plausibility check and a temporal hit show up as payload and persistence.
        Assert.EndsWith("timing=0.000, payload=1.000, ml=1.000, persistence=1.000", alerts[3].Reason);
        Assert.All(alerts, a => Assert.Equal("CRITICAL", a.Severity));
    }

    [Fact]
    public void Severity_follows_the_bands_the_screens_label()
    {
        const string response = @"{ ""anomalies"": [
          {""context"": {""timestamp"": 1.0, ""can_id"": ""0x100"", ""anomaly_score"": 0.80}},
          {""context"": {""timestamp"": 2.0, ""can_id"": ""0x100"", ""anomaly_score"": 0.55}},
          {""context"": {""timestamp"": 3.0, ""can_id"": ""0x100"", ""anomaly_score"": 0.54}}
        ] }";
        var alerts = HomeViewModel.ConvertApiAnomalies(JsonConvert.DeserializeObject<PythonAnalyzeResponse>(response), Array.Empty<PlaybackPacket>());

        Assert.Equal(new[] { "CRITICAL", "WARNING", "INFO" }, alerts.Select(d => d.Alert.Severity));
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
