using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace CANvision.Native.Models;

public sealed class PythonHealthResponse
{
    [JsonProperty("status")]
    public string Status { get; set; } = string.Empty;

    [JsonProperty("service")]
    public string Service { get; set; } = string.Empty;

    [JsonProperty("timestamp")]
    public string Timestamp { get; set; } = string.Empty;
}

public sealed class PythonMetricsResponse
{
    [JsonProperty("status")]
    public string Status { get; set; } = string.Empty;

    [JsonProperty("uptime_seconds")]
    public double UptimeSeconds { get; set; }

    [JsonProperty("requests_total")]
    public int RequestsTotal { get; set; }

    [JsonProperty("analyze_requests_total")]
    public int AnalyzeRequestsTotal { get; set; }

    [JsonProperty("analyzed_rows_total")]
    public int AnalyzedRowsTotal { get; set; }

    [JsonProperty("anomalies_total")]
    public int AnomaliesTotal { get; set; }

    [JsonProperty("avg_analyze_latency_ms")]
    public double AvgAnalyzeLatencyMs { get; set; }

    [JsonProperty("model_loaded")]
    public bool ModelLoaded { get; set; }

    [JsonProperty("model_clusters")]
    public int ModelClusters { get; set; }
}

public sealed class PythonAnalyzeSummary
{
    [JsonProperty("files_received")]
    public int FilesReceived { get; set; }

    [JsonProperty("rows_parsed")]
    public int RowsParsed { get; set; }

    [JsonProperty("anomaly_count")]
    public int AnomalyCount { get; set; }

    [JsonProperty("normal_count")]
    public int NormalCount { get; set; }

    [JsonProperty("cluster_count")]
    public int ClusterCount { get; set; }

    [JsonProperty("parse_lines_total")]
    public int ParseLinesTotal { get; set; }

    [JsonProperty("parse_lines_parsed")]
    public int ParseLinesParsed { get; set; }

    [JsonProperty("parse_lines_skipped")]
    public int ParseLinesSkipped { get; set; }

    [JsonProperty("elapsed_ms")]
    public double ElapsedMs { get; set; }
}

public sealed class PythonAnalyzeItem
{
    [JsonProperty("context")]
    public JObject Context { get; set; } = new();

    [JsonProperty("explanation")]
    public JObject Explanation { get; set; } = new();
}

public sealed class PythonAnalyzeResponse
{
    [JsonProperty("summary")]
    public PythonAnalyzeSummary? Summary { get; set; }

    [JsonProperty("anomalies")]
    public List<PythonAnalyzeItem> Anomalies { get; set; } = new();
}

public sealed class PythonInferenceResponse
{
    [JsonProperty("anomaly_score")]
    public double AnomalyScore { get; set; }

    [JsonProperty("anomaly_label")]
    public string AnomalyLabel { get; set; } = "normal";
}

public sealed class ValidationFrameScore
{
    [JsonProperty("timestamp")]
    public double Timestamp { get; set; }

    [JsonProperty("can_id")]
    public int CanId { get; set; }

    [JsonProperty("score")]
    public double Score { get; set; }

    [JsonProperty("label")]
    public string Label { get; set; } = "normal";

    [JsonProperty("severity")]
    public string Severity { get; set; } = "LOW";
}

public sealed class ValidationScoreResponse
{
    [JsonProperty("status")]
    public string Status { get; set; } = string.Empty;

    [JsonProperty("frame_count")]
    public int FrameCount { get; set; }

    [JsonProperty("anomaly_count")]
    public int AnomalyCount { get; set; }

    [JsonProperty("frames")]
    public List<ValidationFrameScore> Frames { get; set; } = new();
}

public sealed class ReplayStartResponse
{
    [JsonProperty("status")]
    public string Status { get; set; } = string.Empty;

    [JsonProperty("message")]
    public string Message { get; set; } = string.Empty;

    [JsonProperty("input_path")]
    public string InputPath { get; set; } = string.Empty;
}

public sealed class LiveAlertItem
{
    [JsonProperty("timestamp")]
    public double Timestamp { get; set; }

    [JsonProperty("severity")]
    public string Severity { get; set; } = "INFO";

    [JsonProperty("attack_type")]
    public string AttackType { get; set; } = "UNKNOWN";

    [JsonProperty("can_id")]
    public string CanId { get; set; } = "0x000";

    [JsonProperty("score")]
    public double Score { get; set; }

    [JsonProperty("dominant_detection_layer")]
    public string DominantDetectionLayer { get; set; } = string.Empty;

    [JsonProperty("reason")]
    public string Reason { get; set; } = string.Empty;
}

public sealed class LiveAlertsResponse
{
    [JsonProperty("status")]
    public string Status { get; set; } = string.Empty;

    [JsonProperty("items")]
    public List<LiveAlertItem> Items { get; set; } = new();
}

public sealed class LiveSignalItem
{
    [JsonProperty("timestamp")]    public double Timestamp    { get; set; }
    [JsonProperty("can_id")]       public string CanId        { get; set; } = "0x000";
    [JsonProperty("b0")]           public byte   B0           { get; set; }
    [JsonProperty("b1")]           public byte   B1           { get; set; }
    [JsonProperty("b2")]           public byte   B2           { get; set; }
    [JsonProperty("b3")]           public byte   B3           { get; set; }
    [JsonProperty("b4")]           public byte   B4           { get; set; }
    [JsonProperty("b5")]           public byte   B5           { get; set; }
    [JsonProperty("b6")]           public byte   B6           { get; set; }
    [JsonProperty("b7")]           public byte   B7           { get; set; }
    [JsonProperty("anomaly_score")] public double AnomalyScore { get; set; }
    [JsonProperty("severity")]     public string Severity     { get; set; } = "LOW";
}

public sealed class LiveSignalsResponse
{
    [JsonProperty("status")] public string Status { get; set; } = string.Empty;
    [JsonProperty("items")]  public List<LiveSignalItem> Items { get; set; } = new();
}

public sealed class ExplainAlertResponse
{
    [JsonProperty("status")]          public string Status         { get; set; } = string.Empty;
    [JsonProperty("alert_index")]     public int    AlertIndex     { get; set; }
    [JsonProperty("summary")]         public string Summary        { get; set; } = string.Empty;
    [JsonProperty("detail")]          public string Detail         { get; set; } = string.Empty;
    [JsonProperty("recommendation")]  public string Recommendation { get; set; } = string.Empty;
    [JsonProperty("layer_timing")]    public double LayerTiming    { get; set; }
    [JsonProperty("layer_payload")]   public double LayerPayload   { get; set; }
    [JsonProperty("layer_ml")]        public double LayerMl        { get; set; }
    [JsonProperty("layer_temporal")]  public double LayerTemporal  { get; set; }
    [JsonProperty("cached")]          public bool   Cached         { get; set; }
}

public sealed class ReplayStatusResponse
{
    [JsonProperty("status")]
    public string Status { get; set; } = string.Empty;

    [JsonProperty("state")]
    public string State { get; set; } = string.Empty;

    [JsonProperty("input_path")]
    public string InputPath { get; set; } = string.Empty;

    [JsonProperty("started_at")]
    public string StartedAt { get; set; } = string.Empty;

    [JsonProperty("completed_at")]
    public string CompletedAt { get; set; } = string.Empty;

    [JsonProperty("elapsed_seconds")]
    public double? ElapsedSeconds { get; set; }

    [JsonProperty("frames_processed")]
    public int FramesProcessed { get; set; }

    [JsonProperty("total_frames")]
    public int? TotalFrames { get; set; }

    [JsonProperty("results_ready")]
    public bool ResultsReady { get; set; }

    [JsonProperty("error")]
    public string Error { get; set; } = string.Empty;
}
