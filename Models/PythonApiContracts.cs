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

public sealed class DecodedSignalItem
{
    [JsonProperty("signal")]        public string Signal      { get; set; } = string.Empty;
    [JsonProperty("system")]        public string System      { get; set; } = string.Empty;
    [JsonProperty("value")]         public double Value       { get; set; }
    [JsonProperty("unit")]          public string Unit        { get; set; } = string.Empty;
    [JsonProperty("out_of_range")]  public bool   OutOfRange  { get; set; }
    [JsonProperty("delta")]         public double Delta       { get; set; }
    [JsonProperty("nominal")]       public double Nominal     { get; set; }
    [JsonProperty("min_normal")]    public double MinNormal   { get; set; }
    [JsonProperty("max_normal")]    public double MaxNormal   { get; set; }
}

public sealed class ExplainAlertResponse
{
    [JsonProperty("status")]                   public string Status               { get; set; } = string.Empty;
    [JsonProperty("alert_index")]              public int    AlertIndex            { get; set; }
    [JsonProperty("summary")]                  public string Summary              { get; set; } = string.Empty;
    [JsonProperty("detail")]                   public string Detail               { get; set; } = string.Empty;
    [JsonProperty("recommendation")]           public string Recommendation       { get; set; } = string.Empty;
    [JsonProperty("layer_timing")]             public double LayerTiming          { get; set; }
    [JsonProperty("layer_payload")]            public double LayerPayload         { get; set; }
    [JsonProperty("layer_ml")]                 public double LayerMl              { get; set; }
    [JsonProperty("layer_temporal")]           public double LayerTemporal        { get; set; }
    [JsonProperty("cached")]                   public bool   Cached               { get; set; }
    [JsonProperty("kb_match_label")]           public string KbMatchLabel         { get; set; } = string.Empty;
    /// <summary>Which engine produced Summary/Detail/Recommendation: "gemini" | "ollama" | "rule_based".
    /// The UI must show this honestly and never present "rule_based" text as generative AI.</summary>
    [JsonProperty("mode")]                     public string Mode                 { get; set; } = "rule_based";
    [JsonProperty("decoded_signals")]          public List<DecodedSignalItem> DecodedSignals { get; set; } = new();
    [JsonProperty("plausibility_passed")]      public bool   PlausibilityPassed   { get; set; } = true;
    [JsonProperty("plausibility_violations")]  public List<PlausibilityViolation> PlausibilityViolations { get; set; } = new();
    [JsonProperty("timing_anomaly")]           public bool   TimingAnomaly        { get; set; }
    [JsonProperty("timing_score")]             public double TimingScore          { get; set; }
    [JsonProperty("temporal_pattern")]         public string TemporalPattern      { get; set; } = "normal";
    [JsonProperty("temporal_score")]           public double TemporalScore        { get; set; }
    [JsonProperty("detection_layers")]         public List<string> DetectionLayers { get; set; } = new();
}

public sealed class PlausibilityViolation
{
    [JsonProperty("signal")]      public string Signal      { get; set; } = string.Empty;
    [JsonProperty("value")]       public double Value       { get; set; }
    [JsonProperty("min_normal")]  public double MinNormal   { get; set; }
    [JsonProperty("max_normal")]  public double MaxNormal   { get; set; }
    [JsonProperty("unit")]        public string Unit        { get; set; } = string.Empty;
    [JsonProperty("excess")]      public double Excess      { get; set; }
}

public sealed class ChatResponse
{
    [JsonProperty("status")]  public string Status { get; set; } = string.Empty;
    [JsonProperty("reply")]   public string Reply  { get; set; } = string.Empty;
    /// <summary>"gemini" | "ollama" | "rule_based" — which engine produced Reply.</summary>
    [JsonProperty("mode")]    public string Mode   { get; set; } = "rule_based";
}

public sealed class RecordStatusResponse
{
    [JsonProperty("status")]          public string Status         { get; set; } = string.Empty;
    [JsonProperty("is_recording")]    public bool   IsRecording    { get; set; }
    [JsonProperty("frame_count")]     public int    FrameCount     { get; set; }
    [JsonProperty("elapsed_seconds")] public double ElapsedSeconds { get; set; }
    [JsonProperty("output_path")]     public string OutputPath     { get; set; } = string.Empty;
}

public sealed class SessionListItem
{
    [JsonProperty("name")]    public string Name   { get; set; } = string.Empty;
    [JsonProperty("path")]    public string Path   { get; set; } = string.Empty;
    [JsonProperty("size_kb")] public double SizeKb { get; set; }
}

public sealed class SessionListResponse
{
    [JsonProperty("status")]   public string Status { get; set; } = string.Empty;
    [JsonProperty("sessions")] public List<SessionListItem> Sessions { get; set; } = new();
    [JsonProperty("datasets")] public List<SessionListItem> Datasets { get; set; } = new();
}

public sealed class SystemHealthDetailResponse
{
    [JsonProperty("status")]           public string Status          { get; set; } = string.Empty;
    [JsonProperty("fastapi")]          public string FastApi         { get; set; } = string.Empty;
    [JsonProperty("model_loaded")]     public bool   ModelLoaded     { get; set; }
    [JsonProperty("model_clusters")]   public int    ModelClusters   { get; set; }
    [JsonProperty("gemini_configured")]public bool   GeminiConfigured{ get; set; }
    [JsonProperty("ollama_available")] public bool   OllamaAvailable { get; set; }
    [JsonProperty("llm_provider")]     public string LlmProvider     { get; set; } = string.Empty;
    [JsonProperty("simulator_running")]public bool   SimulatorRunning{ get; set; }
    [JsonProperty("replay_state")]     public string ReplayState     { get; set; } = string.Empty;
    [JsonProperty("recording_active")] public bool   RecordingActive { get; set; }
    [JsonProperty("live_fps")]         public double LiveFps         { get; set; }
    [JsonProperty("total_alerts")]     public int    TotalAlerts     { get; set; }
    [JsonProperty("uptime_seconds")]   public double UptimeSeconds   { get; set; }
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

// ---------------------------------------------------------------------------
// Vehicle profiles (GET /api/vehicles)
// ---------------------------------------------------------------------------

public sealed class VehicleProfileItem
{
    [JsonProperty("id")]
    public string Id { get; set; } = string.Empty;

    [JsonProperty("name")]
    public string Name { get; set; } = string.Empty;

    [JsonProperty("bitrate")]
    public int Bitrate { get; set; }

    [JsonProperty("has_uds_dbc")]
    public bool HasUdsDbc { get; set; }

    [JsonProperty("has_raw_dbc")]
    public bool HasRawDbc { get; set; }

    [JsonProperty("has_transmit_list")]
    public bool HasTransmitList { get; set; }
}

public sealed class VehicleListResponse
{
    [JsonProperty("status")]
    public string Status { get; set; } = string.Empty;

    [JsonProperty("vehicles")]
    public List<VehicleProfileItem> Vehicles { get; set; } = new();
}

// ---------------------------------------------------------------------------
// Offline session analysis  (POST /api/offline/analyze + GET /api/offline/status/{id})
// ---------------------------------------------------------------------------

public sealed class OfflineAnalyzeStartResponse
{
    [JsonProperty("status")]
    public string Status { get; set; } = string.Empty;

    [JsonProperty("session_id")]
    public string SessionId { get; set; } = string.Empty;
}

// ---------------------------------------------------------------------------
// MF4 -> CSV conversion bridge  (POST /api/mf4/convert)
// ---------------------------------------------------------------------------

public sealed class Mf4ConvertResponse
{
    [JsonProperty("status")]
    public string Status { get; set; } = string.Empty;

    [JsonProperty("csv_path")]
    public string CsvPath { get; set; } = string.Empty;
}

public sealed class OfflineSessionStatus
{
    [JsonProperty("session_id")]
    public string SessionId { get; set; } = string.Empty;

    [JsonProperty("status")]
    public string Status { get; set; } = string.Empty;   // pending | running | done | error

    [JsonProperty("progress")]
    public double Progress { get; set; }

    [JsonProperty("total_frames")]
    public int TotalFrames { get; set; }

    [JsonProperty("processed_frames")]
    public int ProcessedFrames { get; set; }

    [JsonProperty("anomaly_count")]
    public int AnomalyCount { get; set; }

    [JsonProperty("error")]
    public string Error { get; set; } = string.Empty;

    [JsonProperty("vehicle_id")]
    public string VehicleId { get; set; } = string.Empty;

    [JsonProperty("file_path")]
    public string FilePath { get; set; } = string.Empty;

    [JsonProperty("output_path")]
    public string OutputPath { get; set; } = string.Empty;

    [JsonProperty("completed_at")]
    public string CompletedAt { get; set; } = string.Empty;
}

public sealed class OfflineSummaryResponse
{
    [JsonProperty("session_id")]
    public string SessionId { get; set; } = string.Empty;

    [JsonProperty("status")]
    public string Status { get; set; } = string.Empty;

    [JsonProperty("vehicle_id")]
    public string VehicleId { get; set; } = string.Empty;

    [JsonProperty("total_frames")]
    public int TotalFrames { get; set; }

    [JsonProperty("anomaly_count")]
    public int AnomalyCount { get; set; }

    [JsonProperty("anomaly_rate")]
    public double AnomalyRate { get; set; }

    [JsonProperty("decoded_signals")]
    public List<string> DecodedSignals { get; set; } = new();

    [JsonProperty("top_threats")]
    public List<OfflineTopThreat> TopThreats { get; set; } = new();
}

public sealed class OfflineTopThreat
{
    [JsonProperty("can_id")]
    public string CanId { get; set; } = string.Empty;

    [JsonProperty("avg_score")]
    public double AvgScore { get; set; }

    [JsonProperty("count")]
    public int Count { get; set; }
}

// ---------------------------------------------------------------------------
// Aggregated decoded engineering signals  (GET /api/live/decoded-signals)
// ---------------------------------------------------------------------------

public sealed class LiveDecodedSignalEntry
{
    [JsonProperty("name")]         public string Name        { get; set; } = string.Empty;
    [JsonProperty("can_id")]       public string CanId       { get; set; } = string.Empty;
    [JsonProperty("value")]        public double Value       { get; set; }
    [JsonProperty("unit")]         public string Unit        { get; set; } = string.Empty;
    [JsonProperty("system")]       public string System      { get; set; } = string.Empty;
    [JsonProperty("out_of_range")] public bool   OutOfRange  { get; set; }
}

public sealed class LiveDecodedSignalsResponse
{
    [JsonProperty("status")] public string Status { get; set; } = string.Empty;
    [JsonProperty("items")]  public List<LiveDecodedSignalEntry> Items { get; set; } = new();
}

// ---------------------------------------------------------------------------
// Live hardware CAN interface  (POST /api/live/hardware/connect + disconnect)
// ---------------------------------------------------------------------------

public sealed class HardwareStatusResponse
{
    [JsonProperty("is_connected")]
    public bool IsConnected { get; set; }

    [JsonProperty("interface_type")]
    public string InterfaceType { get; set; } = string.Empty;

    [JsonProperty("channel")]
    public string Channel { get; set; } = string.Empty;

    [JsonProperty("vehicle_id")]
    public string VehicleId { get; set; } = string.Empty;

    [JsonProperty("frames_received")]
    public long FramesReceived { get; set; }

    [JsonProperty("alert_count")]
    public int AlertCount { get; set; }

    [JsonProperty("current_score")]
    public double CurrentScore { get; set; }

    [JsonProperty("uptime_seconds")]
    public double UptimeSeconds { get; set; }

    [JsonProperty("error")]
    public string Error { get; set; } = string.Empty;
}

// ---------------------------------------------------------------------------
// Hardware port discovery  (GET /api/live/hardware/ports)
// ---------------------------------------------------------------------------

public sealed class HardwarePortInfo
{
    [JsonProperty("name")]
    public string Name { get; set; } = string.Empty;

    [JsonProperty("description")]
    public string Description { get; set; } = string.Empty;

    [JsonProperty("hwid")]
    public string HwId { get; set; } = string.Empty;
}

public sealed class HardwarePortsResponse
{
    [JsonProperty("ports")]
    public List<HardwarePortInfo> Ports { get; set; } = new();
}

// ---------------------------------------------------------------------------
// python-can availability check  (GET /api/live/hardware/check)
// ---------------------------------------------------------------------------

public sealed class HardwareCheckResponse
{
    [JsonProperty("python_can_available")]
    public bool PythonCanAvailable { get; set; }

    [JsonProperty("python_can_version")]
    public string PythonCanVersion { get; set; } = string.Empty;

    [JsonProperty("pyserial_available")]
    public bool PyserialAvailable { get; set; }

    [JsonProperty("supported_interfaces")]
    public List<string> SupportedInterfaces { get; set; } = new();
}
