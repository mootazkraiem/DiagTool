# CAN AI Diagnostic System Audit And Upgrade Report

## Phase 1: System Audit

### 1) Parser Correctness
- Status: Improved.
- Original weakness:
1. Only two line formats were parsed.
2. ASC and mixed CSV-like logs were often skipped.
3. No parse-quality stats.
- Upgrade:
1. Added multi-format parsing (`candump`, `ASC Rx/Tx d`, and fallback `ID#DATA` extraction).
2. Added `ParseStats` (`lines_total`, `lines_parsed`, `lines_skipped`) for auditability.
3. Added stream parsing for large-file handling.

### 2) Feature Engineering Completeness
- Status: Upgraded to professional feature set.
- Original weakness:
1. No rolling stats.
2. No entropy feature.
3. No time-window frequency.
- Upgrade:
1. Added `window_frequency` with configurable time windows.
2. Added rolling statistics: `rolling_mean_8`, `rolling_std_8`.
3. Added `payload_entropy` for byte variability.
4. Kept NaN/infinity sanitation.

### 3) Model Training Validity
- Status: Improved and productionized.
- Original weakness:
1. No persistence.
2. Fixed cluster count.
3. No severity normalization.
- Upgrade:
1. Added model save/load with `joblib`.
2. Added elbow-style automatic cluster selection.
3. Added severity score (0 to 1) from IsolationForest decision score.
4. Added cluster profiling for interpretability.

### 4) API Functionality
- Status: Hardened.
- Original weakness:
1. No response schemas.
2. No metrics endpoint.
3. Limited error response model.
- Upgrade:
1. Added strict Pydantic request/response schemas.
2. Added `/metrics` endpoint.
3. Added global exception handling and typed error payload.
4. Added analysis cache for repeated files.
5. Preserved `/vehicle` for C# compatibility.

### 5) LLM Integration
- Status: Upgraded prompt quality and structure.
- Original weakness:
1. Prompt missed severity and anomaly type.
2. Prompt lacked cluster behavior details.
- Upgrade:
1. Prompt now includes severity, anomaly type, confidence, cluster profile, and z-scores.
2. Enforced structured JSON output keys: `causes`, `risks`, `recommendations`.
3. Added graceful fallback on SDK/network failure.

## Phase 2: Professional Improvements Implemented

### Data And Features
1. `StandardScaler` retained and validated in model pipeline.
2. Rolling mean/std added.
3. Entropy added.
4. Time-window frequency added.

### Model
1. Kept Isolation Forest with `decision_function`.
2. Added normalized severity score `0..1`.
3. Added persistent model bundle (`data/can_ai_model.joblib`).

### Clustering
1. Added elbow-like auto-cluster selection.
2. Added cluster profiling summary (`rows`, average frequency/entropy/timing).

### Performance
1. Added streaming parser for large files.
2. Added in-memory SHA256 cache for repeated uploads.
3. Reduced duplicate parse work.

### Reliability
1. Added robust logging (`info`, `warning`, `error`).
2. Added global API exception handler.
3. Added typed validation for feedback (`can_id`, `label`).

## Phase 3: Advanced Anomaly Intelligence

Output now includes:
```json
{
  "can_id": "0x1A2",
  "severity": 0.92,
  "type": "frequency_anomaly",
  "cluster": 2,
  "confidence": "high"
}
```

Type classification logic:
1. `frequency_anomaly` from strong frequency z-score drift.
2. `timing_anomaly` from inter-arrival timing z-score drift.
3. `data_anomaly` from unusual byte z-score behavior.
4. `pattern_anomaly` fallback.

## Phase 4: LLM Upgrade

Prompt now includes:
1. Severity.
2. Anomaly type.
3. Cluster profile.
4. Frequency and timing deviations.
5. Unusual byte summary.

Output contract:
1. `causes`
2. `risks`
3. `recommendations`

## Phase 5: API Hardening

Endpoints:
1. `GET /health`
2. `GET /vehicle`
3. `POST /analyze`
4. `POST /feedback`
5. `GET /metrics`

Hardening details:
1. Request validation and response models.
2. Structured error schema.
3. Runtime metrics and latency tracking.
4. Startup seed training from `assets/EV-CANlogs-main`.

## Performance Notes
1. LLM calls per anomaly can dominate latency; consider async batching in future.
2. Startup training cost scales with seed file count; bounded by parser limits.
3. Cache is process-memory only; restart clears it.

## Known Limitations
1. No DBC decoding by design (vehicle-agnostic tradeoff).
2. Format support is best-effort for many real logs but not guaranteed for every vendor custom export.
3. Cluster semantics are statistical, not OEM semantic labels.

## Changed Files
1. `core/diagnostic_backend.py`
2. `python_api_server.py`
3. `requirements.txt`
4. `docs/CAN_AI_AUDIT_REPORT.md`
