using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net.Http.Headers;
using System.Text;
using System.Net.Http;
using CANvision.Native.Models;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using Microsoft.Win32;

namespace CANvision.Native.Services;

public sealed class PythonApiClient
{
    private const string DefaultEndpoint = "http://127.0.0.1:8765/vehicle";

    private readonly HttpClient httpClient = new() { Timeout = TimeSpan.FromMinutes(5) };
    private readonly AppLogger logger;
    private readonly string endpoint;
    private readonly string apiBase;
    private readonly string jsonFallbackPath;

    public PythonApiClient(AppLogger logger)
    {
        this.logger = logger;
        endpoint = Environment.GetEnvironmentVariable("CANVISION_PYTHON_API") ?? DefaultEndpoint;
        apiBase = BuildApiBase(endpoint);
        jsonFallbackPath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "data", "vehicle-state.json");
    }

    public string Endpoint => endpoint;
    public string ApiBase => apiBase;

    public string JsonFallbackPath => jsonFallbackPath;

    public async Task<VehicleSnapshot?> GetLatestSnapshotAsync(CancellationToken cancellationToken)
    {
        var fromApi = await TryFetchFromApiAsync(cancellationToken);
        if (fromApi is not null)
        {
            return fromApi;
        }

        return await TryFetchFromFileAsync(cancellationToken);
    }

    public async Task<PythonHealthResponse?> GetHealthAsync(CancellationToken cancellationToken)
    {
        return await GetJsonAsync<PythonHealthResponse>("health", cancellationToken);
    }

    public async Task<PythonMetricsResponse?> GetMetricsAsync(CancellationToken cancellationToken)
    {
        return await GetJsonAsync<PythonMetricsResponse>("metrics", cancellationToken);
    }

    public async Task<PythonAnalyzeResponse?> AnalyzeLogsAsync(IEnumerable<string> filePaths, CancellationToken cancellationToken)
    {
        var files = (filePaths ?? Enumerable.Empty<string>())
            .Where(path => !string.IsNullOrWhiteSpace(path) && File.Exists(path))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();

        if (files.Count == 0)
        {
            logger.Info("AnalyzeLogsAsync called with no valid files.");
            return null;
        }

        try
        {
            using var multipart = new MultipartFormDataContent();
            foreach (var file in files)
            {
                var bytes = await Task.Run(() => File.ReadAllBytes(file), cancellationToken);
                var part = new ByteArrayContent(bytes);
                part.Headers.ContentType = new MediaTypeHeaderValue("application/octet-stream");
                multipart.Add(part, "files", Path.GetFileName(file));
            }

            using var response = await httpClient.PostAsync(BuildUrl("analyze"), multipart, cancellationToken);
            if (!response.IsSuccessStatusCode)
            {
                logger.Info($"Python analyze endpoint returned {(int)response.StatusCode}.");
                return null;
            }

            var json = await response.Content.ReadAsStringAsync();
            var payload = JsonConvert.DeserializeObject<PythonAnalyzeResponse>(json);
            return payload;
        }
        catch (Exception exception)
        {
            logger.Error("AnalyzeLogsAsync failed.", exception);
            return null;
        }
    }

    public async Task<MlInferenceResult?> ScoreFeatureVectorAsync(IReadOnlyList<double> featureVector, CancellationToken cancellationToken)
    {
        try
        {
            var payload = new JObject
            {
                ["features"] = new JArray(featureVector.ToArray())
            };

            using var content = new StringContent(payload.ToString(Formatting.None), Encoding.UTF8, "application/json");
            using var response = await httpClient.PostAsync(BuildUrl("infer"), content, cancellationToken);
            if (response.IsSuccessStatusCode)
            {
                var json = await response.Content.ReadAsStringAsync();
                var parsed = JsonConvert.DeserializeObject<PythonInferenceResponse>(json);
                if (parsed is not null)
                {
                    return new MlInferenceResult(parsed.AnomalyScore, parsed.AnomalyLabel, Math.Min(100, Math.Abs(parsed.AnomalyScore) * 100.0));
                }
            }
        }
        catch (Exception exception)
        {
            logger.Error("Feature-vector inference endpoint failed.", exception);
        }

        return null;
    }

    public async Task<MlInferenceResult?> InferFrameAsync(
        double timestamp,
        int canId,
        IReadOnlyList<byte> payload,
        string vehicle,
        CancellationToken cancellationToken)
    {
        try
        {
            var bytes = payload.Concat(Enumerable.Repeat<byte>(0, Math.Max(0, 8 - payload.Count))).Take(8).ToArray();
            var payloadJson = new JObject
            {
                ["timestamp"] = timestamp,
                ["can_id"] = canId,
                ["b0"] = bytes.ElementAtOrDefault(0),
                ["b1"] = bytes.ElementAtOrDefault(1),
                ["b2"] = bytes.ElementAtOrDefault(2),
                ["b3"] = bytes.ElementAtOrDefault(3),
                ["b4"] = bytes.ElementAtOrDefault(4),
                ["b5"] = bytes.ElementAtOrDefault(5),
                ["b6"] = bytes.ElementAtOrDefault(6),
                ["b7"] = bytes.ElementAtOrDefault(7),
                ["vehicle"] = string.IsNullOrWhiteSpace(vehicle) ? "kaggle_normal" : vehicle,
            };

            using var content = new StringContent(payloadJson.ToString(Formatting.None), Encoding.UTF8, "application/json");
            using var response = await httpClient.PostAsync(BuildUrl("infer"), content, cancellationToken);
            if (!response.IsSuccessStatusCode)
            {
                logger.Info($"Python infer endpoint returned {(int)response.StatusCode}.");
                return null;
            }

            var json = await response.Content.ReadAsStringAsync();
            var parsed = JsonConvert.DeserializeObject<PythonInferenceResponse>(json);
            if (parsed is null)
            {
                return null;
            }

            return new MlInferenceResult(parsed.AnomalyScore, parsed.AnomalyLabel, Math.Min(100, Math.Abs(parsed.AnomalyScore) * 100.0));
        }
        catch (Exception exception)
        {
            logger.Error("Frame inference endpoint failed.", exception);
            return null;
        }
    }

    public async Task StartLiveSessionAsync(CancellationToken cancellationToken)
    {
        try
        {
            using var response = await httpClient.PostAsync(BuildUrl("api/live/start"), new StringContent(string.Empty), cancellationToken);
            if (!response.IsSuccessStatusCode)
                logger.Info($"Live start endpoint returned {(int)response.StatusCode}.");
        }
        catch (Exception exception)
        {
            logger.Error("StartLiveSessionAsync failed.", exception);
        }
    }

    public async Task<LiveAlertsResponse?> GetLiveAlertsAsync(CancellationToken cancellationToken)
    {
        return await GetJsonAsync<LiveAlertsResponse>("api/live/alerts", cancellationToken);
    }

    public async Task<LiveSignalsResponse?> GetLiveSignalsAsync(int limit, CancellationToken cancellationToken)
    {
        return await GetJsonAsync<LiveSignalsResponse>($"api/live/signals?limit={limit}", cancellationToken);
    }

    public async Task<ExplainAlertResponse?> GetAlertExplanationAsync(int alertIndex, CancellationToken cancellationToken)
    {
        return await GetJsonAsync<ExplainAlertResponse>($"api/explain/{alertIndex}", cancellationToken);
    }

    public async Task<ChatResponse?> ChatAsync(
        string canId, double score, string severity, string attackType, string reason,
        string message, CancellationToken cancellationToken)
    {
        try
        {
            var alert = new JObject
            {
                ["can_id"]      = canId,
                ["score"]       = score,
                ["severity"]    = severity,
                ["attack_type"] = attackType,
                ["reason"]      = reason,
                ["dominant_detection_layer"] = "ml",
            };
            var payload = new JObject { ["message"] = message, ["alert"] = alert };
            using var content = new StringContent(payload.ToString(Formatting.None), Encoding.UTF8, "application/json");
            using var response = await httpClient.PostAsync(BuildUrl("api/chat"), content, cancellationToken);
            if (!response.IsSuccessStatusCode) return null;
            var json = await response.Content.ReadAsStringAsync();
            return JsonConvert.DeserializeObject<ChatResponse>(json);
        }
        catch (Exception exception)
        {
            logger.Error("ChatAsync failed.", exception);
            return null;
        }
    }

    public async Task StopLiveSessionAsync(CancellationToken cancellationToken)
    {
        try
        {
            using var response = await httpClient.PostAsync(BuildUrl("api/live/stop"), new StringContent(string.Empty), cancellationToken);
            if (!response.IsSuccessStatusCode)
                logger.Info($"Live stop endpoint returned {(int)response.StatusCode}.");
        }
        catch (Exception exception)
        {
            logger.Error("StopLiveSessionAsync failed.", exception);
        }
    }

    public async Task<ValidationScoreResponse?> ScoreValidationFileAsync(string filePath, CancellationToken cancellationToken)
    {
        try
        {
            var payload = new JObject { ["input_path"] = filePath };
            using var content = new StringContent(payload.ToString(Formatting.None), Encoding.UTF8, "application/json");
            using var response = await httpClient.PostAsync(BuildUrl("api/validation/score_file"), content, cancellationToken);
            if (!response.IsSuccessStatusCode)
            {
                logger.Info($"Python validation score endpoint returned {(int)response.StatusCode}.");
                return null;
            }

            var json = await response.Content.ReadAsStringAsync();
            return JsonConvert.DeserializeObject<ValidationScoreResponse>(json);
        }
        catch (Exception exception)
        {
            logger.Error("ScoreValidationFileAsync failed.", exception);
            return null;
        }
    }

    public async Task<ReplayStartResponse?> StartReplayAsync(string inputPath, int limit, string vehicleId, CancellationToken cancellationToken)
    {
        try
        {
            var payload = new JObject
            {
                ["input_path"] = inputPath,
                ["limit"] = limit,
                ["vehicle_id"] = vehicleId ?? string.Empty,
            };
            using var content = new StringContent(payload.ToString(Formatting.None), Encoding.UTF8, "application/json");
            using var response = await httpClient.PostAsync(BuildUrl("api/replay/start"), content, cancellationToken);
            if (!response.IsSuccessStatusCode) return null;
            var json = await response.Content.ReadAsStringAsync();
            return JsonConvert.DeserializeObject<ReplayStartResponse>(json);
        }
        catch (Exception exception)
        {
            logger.Error("StartReplayAsync failed.", exception);
            return null;
        }
    }

    public async Task<ReplayStatusResponse?> GetReplayStatusAsync(CancellationToken cancellationToken)
    {
        return await GetJsonAsync<ReplayStatusResponse>("api/replay/status", cancellationToken);
    }

    public async Task<LiveAlertsResponse?> GetReplayAlertsAsync(CancellationToken cancellationToken)
    {
        return await GetJsonAsync<LiveAlertsResponse>("api/replay/alerts", cancellationToken);
    }

    public async Task<LiveAlertsResponse?> GetPartialReplayAlertsAsync(CancellationToken cancellationToken)
    {
        return await GetJsonAsync<LiveAlertsResponse>("api/replay/partial-alerts", cancellationToken);
    }

    public async Task<bool> StopReplayAsync(CancellationToken cancellationToken)
    {
        try
        {
            using var response = await httpClient.PostAsync(BuildUrl("api/replay/stop"), new StringContent(string.Empty), cancellationToken);
            return response.IsSuccessStatusCode;
        }
        catch (Exception exception)
        {
            logger.Error("StopReplayAsync failed.", exception);
            return false;
        }
    }

    private async Task<VehicleSnapshot?> TryFetchFromApiAsync(CancellationToken cancellationToken)
    {
        try
        {
            using var response = await httpClient.GetAsync(BuildUrl("vehicle"), cancellationToken);
            if (!response.IsSuccessStatusCode)
            {
                logger.Info($"Python API returned {(int)response.StatusCode}; falling back to local JSON.");
                return null;
            }

            var json = await response.Content.ReadAsStringAsync();
            var snapshot = JsonConvert.DeserializeObject<VehicleSnapshot>(json);
            if (snapshot is null)
            {
                logger.Info("Python API returned empty payload; falling back to local JSON.");
                return null;
            }

            snapshot.Source = string.IsNullOrWhiteSpace(snapshot.Source) ? "python-api" : snapshot.Source;
            if (snapshot.UpdatedAt == default)
            {
                snapshot.UpdatedAt = DateTime.UtcNow;
            }

            return snapshot;
        }
        catch (Exception exception)
        {
            logger.Error($"Python API fetch failed at {endpoint}.", exception);
            return null;
        }
    }

    private async Task<VehicleSnapshot?> TryFetchFromFileAsync(CancellationToken cancellationToken)
    {
        try
        {
            if (!File.Exists(jsonFallbackPath))
            {
                logger.Info($"Fallback JSON not found at {jsonFallbackPath}.");
                return null;
            }

            var json = await Task.Run(() => File.ReadAllText(jsonFallbackPath), cancellationToken);
            var snapshot = JsonConvert.DeserializeObject<VehicleSnapshot>(json);
            if (snapshot is null)
            {
                logger.Info("Fallback JSON was present but empty.");
                return null;
            }

            snapshot.Source = string.IsNullOrWhiteSpace(snapshot.Source) ? "json-fallback" : snapshot.Source;
            if (snapshot.UpdatedAt == default)
            {
                snapshot.UpdatedAt = DateTime.UtcNow;
            }

            return snapshot;
        }
        catch (Exception exception)
        {
            logger.Error($"Fallback JSON read failed at {jsonFallbackPath}.", exception);
            return null;
        }
    }

    public async Task<RecordStatusResponse?> StartRecordingAsync(CancellationToken cancellationToken)
    {
        try
        {
            using var response = await httpClient.PostAsync(BuildUrl("api/session/record/start"), new StringContent(string.Empty), cancellationToken);
            var json = await response.Content.ReadAsStringAsync();
            return JsonConvert.DeserializeObject<RecordStatusResponse>(json);
        }
        catch (Exception exception)
        {
            logger.Error("StartRecording failed.", exception);
            return null;
        }
    }

    public async Task<RecordStatusResponse?> StopRecordingAsync(CancellationToken cancellationToken)
    {
        try
        {
            using var response = await httpClient.PostAsync(BuildUrl("api/session/record/stop"), new StringContent(string.Empty), cancellationToken);
            var json = await response.Content.ReadAsStringAsync();
            return JsonConvert.DeserializeObject<RecordStatusResponse>(json);
        }
        catch (Exception exception)
        {
            logger.Error("StopRecording failed.", exception);
            return null;
        }
    }

    public async Task<RecordStatusResponse?> GetRecordStatusAsync(CancellationToken cancellationToken)
        => await GetJsonAsync<RecordStatusResponse>("api/session/record/status", cancellationToken);

    public async Task<SessionListResponse?> GetSessionListAsync(CancellationToken cancellationToken)
        => await GetJsonAsync<SessionListResponse>("api/session/list", cancellationToken);

    public async Task<SystemHealthDetailResponse?> GetSystemHealthDetailAsync(CancellationToken cancellationToken)
        => await GetJsonAsync<SystemHealthDetailResponse>("api/system/health", cancellationToken);

    // ── Vehicle profiles ────────────────────────────────────────────────────

    public async Task<VehicleListResponse?> GetVehicleListAsync(CancellationToken cancellationToken)
        => await GetJsonAsync<VehicleListResponse>("api/vehicles", cancellationToken);

    // ── Offline session analysis ─────────────────────────────────────────────

    public async Task<OfflineAnalyzeStartResponse?> StartOfflineAnalysisAsync(
        string filePath, string vehicleId, CancellationToken cancellationToken)
    {
        try
        {
            var payload = new JObject { ["file_path"] = filePath, ["vehicle_id"] = vehicleId };
            using var content = new StringContent(payload.ToString(Formatting.None), Encoding.UTF8, "application/json");
            using var response = await httpClient.PostAsync(BuildUrl("api/offline/analyze"), content, cancellationToken);
            if (!response.IsSuccessStatusCode)
            {
                logger.Info($"Offline analyze returned {(int)response.StatusCode}.");
                return null;
            }
            var json = await response.Content.ReadAsStringAsync();
            return JsonConvert.DeserializeObject<OfflineAnalyzeStartResponse>(json);
        }
        catch (Exception exception)
        {
            logger.Error("StartOfflineAnalysisAsync failed.", exception);
            return null;
        }
    }

    public async Task<OfflineSessionStatus?> GetOfflineStatusAsync(string sessionId, CancellationToken cancellationToken)
        => await GetJsonAsync<OfflineSessionStatus>($"api/offline/status/{sessionId}", cancellationToken);

    public async Task<OfflineSummaryResponse?> GetOfflineSummaryAsync(string sessionId, CancellationToken cancellationToken)
        => await GetJsonAsync<OfflineSummaryResponse>($"api/offline/summary/{sessionId}", cancellationToken);

    // ── MF4 -> CSV conversion bridge ─────────────────────────────────────────
    // Decodes an MF4 recording to CSV via the existing asammdf-based converter
    // so the caller can feed the resulting path into the normal CSV replay
    // pipeline unchanged (no separate MF4 code path to maintain downstream).

    public async Task<string?> ConvertMf4Async(string filePath, CancellationToken cancellationToken)
    {
        try
        {
            var payload = new JObject { ["file_path"] = filePath };
            using var content = new StringContent(payload.ToString(Formatting.None), Encoding.UTF8, "application/json");
            using var response = await httpClient.PostAsync(BuildUrl("api/mf4/convert"), content, cancellationToken);
            if (!response.IsSuccessStatusCode)
            {
                var body = await response.Content.ReadAsStringAsync();
                logger.Error($"MF4 conversion returned {(int)response.StatusCode}: {body}");
                return null;
            }
            var json = await response.Content.ReadAsStringAsync();
            var parsed = JsonConvert.DeserializeObject<Mf4ConvertResponse>(json);
            return string.IsNullOrWhiteSpace(parsed?.CsvPath) ? null : parsed!.CsvPath;
        }
        catch (Exception exception)
        {
            logger.Error("ConvertMf4Async failed.", exception);
            return null;
        }
    }

    // ── Aggregated decoded signals ───────────────────────────────────────────

    public async Task<LiveDecodedSignalsResponse?> GetLiveDecodedSignalsAsync(CancellationToken cancellationToken)
        => await GetJsonAsync<LiveDecodedSignalsResponse>("api/live/decoded-signals", cancellationToken);

    // ── Live hardware CAN interface ──────────────────────────────────────────

    public async Task<bool> ConnectHardwareAsync(
        string interfaceType, string channel, int bitrate, string vehicleId,
        CancellationToken cancellationToken)
    {
        try
        {
            var payload = new JObject
            {
                ["interface"]  = interfaceType,
                ["channel"]    = channel,
                ["bitrate"]    = bitrate,
                ["vehicle_id"] = vehicleId,
            };
            using var content  = new StringContent(payload.ToString(Formatting.None), Encoding.UTF8, "application/json");
            using var response = await httpClient.PostAsync(BuildUrl("api/live/hardware/connect"), content, cancellationToken);
            return response.IsSuccessStatusCode;
        }
        catch (Exception exception)
        {
            logger.Error("ConnectHardwareAsync failed.", exception);
            return false;
        }
    }

    public async Task<bool> DisconnectHardwareAsync(CancellationToken cancellationToken)
    {
        try
        {
            using var content  = new StringContent("{}", Encoding.UTF8, "application/json");
            using var response = await httpClient.PostAsync(BuildUrl("api/live/hardware/disconnect"), content, cancellationToken);
            return response.IsSuccessStatusCode;
        }
        catch (Exception exception)
        {
            logger.Error("DisconnectHardwareAsync failed.", exception);
            return false;
        }
    }

    public async Task<HardwareStatusResponse?> GetHardwareStatusAsync(CancellationToken cancellationToken)
        => await GetJsonAsync<HardwareStatusResponse>("api/live/hardware/status", cancellationToken);

    public async Task<HardwarePortsResponse?> GetHardwarePortsAsync(CancellationToken cancellationToken)
        => await GetJsonAsync<HardwarePortsResponse>("api/live/hardware/ports", cancellationToken);

    public async Task<HardwareCheckResponse?> GetHardwareCheckAsync(CancellationToken cancellationToken)
        => await GetJsonAsync<HardwareCheckResponse>("api/live/hardware/check", cancellationToken);

    private async Task<T?> GetJsonAsync<T>(string relativePath, CancellationToken cancellationToken)
    {
        try
        {
            using var response = await httpClient.GetAsync(BuildUrl(relativePath), cancellationToken);
            if (!response.IsSuccessStatusCode)
            {
                logger.Info($"Python API {relativePath} returned {(int)response.StatusCode}.");
                return default;
            }

            var json = await response.Content.ReadAsStringAsync();
            return JsonConvert.DeserializeObject<T>(json);
        }
        catch (Exception exception) when (exception is System.Net.Http.HttpRequestException || exception is OperationCanceledException)
        {
            // Connection refused / timeout — expected when backend is starting. One-line only.
            logger.Info($"Python API unavailable: {relativePath} ({exception.GetType().Name})");
            return default;
        }
        catch (Exception exception)
        {
            logger.Error($"Python API request failed for {relativePath}.", exception);
            return default;
        }
    }

    private string BuildUrl(string relativePath)
    {
        var clean = relativePath.Trim('/');
        return $"{apiBase}/{clean}";
    }

    private static string BuildApiBase(string configuredEndpoint)
    {
        if (!Uri.TryCreate(configuredEndpoint, UriKind.Absolute, out var uri))
        {
            return "http://127.0.0.1:8765";
        }

        var authority = $"{uri.Scheme}://{uri.Authority}";
        var path = uri.AbsolutePath.TrimEnd('/').ToLowerInvariant();
        if (path.EndsWith("/vehicle"))
        {
            return authority;
        }

        return $"{authority}{uri.AbsolutePath.TrimEnd('/')}";
    }

}

public sealed class MlInferenceResult
{
    public MlInferenceResult(double score, string label, double severityScore)
    {
        Score = score;
        Label = label;
        SeverityScore = severityScore;
    }

    public double Score { get; }
    public string Label { get; }
    public double SeverityScore { get; }
}
