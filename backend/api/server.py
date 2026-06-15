from __future__ import annotations

import io
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional
import threading
import subprocess
import glob
import os

import pandas as pd
import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from backend.data_processing.parser import CanLogParser
from backend.data_processing.feature_engineering import FeatureEngineer
from backend.ml.engine import (
    AnalyzeCache,
    FeedbackStore,
    LLMExplainer,
    VehicleAIDiagnosticEngine,
    collect_can_logs_from_assets,
)
from backend.api.mock_signals import MockSignals
from backend.ml.runtime.realtime_engine import RealtimeEngine, CanFrame
from backend.ml.runtime.ids_statistics import IDSStatistics
from backend.ml.runtime.runtime_config import VALIDATION_CONFIG


logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger("can_ai_backend.api")


class ErrorResponse(BaseModel):
    error: str
    detail: str


class HealthResponse(BaseModel):
    status: str
    service: str
    timestamp: str


class VehicleResponse(BaseModel):
    source: str
    updated_at: str
    battery: int
    temperature: int
    motor_status: str


class FeedbackItem(BaseModel):
    can_id: str = Field(..., description="CAN ID in hex format, e.g., 0x1A2")
    timestamp: float
    label: str = Field(..., description="normal or fault")
    notes: str = ""

    @field_validator("can_id")
    @classmethod
    def validate_can_id(cls, value: str) -> str:
        if not value.startswith("0x"):
            raise ValueError("can_id must start with 0x")
        int(value, 16)
        return value.upper()

    @field_validator("label")
    @classmethod
    def validate_label(cls, value: str) -> str:
        val = value.strip().lower()
        if val not in {"normal", "fault"}:
            raise ValueError("label must be one of: normal, fault")
        return val


class FeedbackResponse(BaseModel):
    status: str


class MetricsResponse(BaseModel):
    status: str
    uptime_seconds: float
    requests_total: int
    analyze_requests_total: int
    analyzed_rows_total: int
    anomalies_total: int
    avg_analyze_latency_ms: float
    model_loaded: bool
    model_clusters: int


class AnalyzeSummary(BaseModel):
    files_received: int
    rows_parsed: int
    anomaly_count: int
    normal_count: int
    cluster_count: int
    parse_lines_total: int
    parse_lines_parsed: int
    parse_lines_skipped: int
    elapsed_ms: float


class AnalyzeResult(BaseModel):
    context: dict[str, object]
    explanation: dict[str, str]


class AnalyzeResponse(BaseModel):
    summary: AnalyzeSummary
    anomalies: list[AnalyzeResult]


class LiveSignalDto(BaseModel):
    timestamp: float
    can_id: str
    b0: int
    b1: int
    b2: int
    b3: int
    b4: int
    b5: int
    b6: int
    b7: int
    anomaly_score: float
    severity: str


class LiveAlertDto(BaseModel):
    timestamp: float
    severity: str
    attack_type: str
    can_id: str
    score: float
    dominant_detection_layer: str
    reason: str
    replay_source: str


class InferRequest(BaseModel):
    timestamp: float = 0.0
    can_id: int = 0
    b0: int = 0
    b1: int = 0
    b2: int = 0
    b3: int = 0
    b4: int = 0
    b5: int = 0
    b6: int = 0
    b7: int = 0
    vehicle: str = "kaggle_normal"
    features: Optional[List[float]] = None


class InferResponse(BaseModel):
    anomaly_score: float
    anomaly_label: str
    severity: str
    vehicle_state: str


class ValidationScoreRequest(BaseModel):
    input_path: str
    limit: int = 0


class ValidationFrameScore(BaseModel):
    timestamp: float
    can_id: int
    score: float
    label: str
    severity: str


class ValidationScoreResponse(BaseModel):
    status: str
    frame_count: int
    anomaly_count: int
    frames: list[ValidationFrameScore]


class ReplayStartRequest(BaseModel):
    input_path: str
    limit: int = 0


class SimulatorGenerateRequest(BaseModel):
    attack: str = "none"
    frames: int = 5000
    intensity: float = 0.5
    output_path: str = "backend/ml/outputs/replay_logs/simulated_traffic.csv"


# Work around Python 3.13 + postponed annotations edge cases in OpenAPI schema generation.
AnalyzeSummary.model_rebuild(_types_namespace=globals())
AnalyzeResult.model_rebuild(_types_namespace=globals())
AnalyzeResponse.model_rebuild(_types_namespace=globals())
ValidationScoreResponse.model_rebuild(_types_namespace=globals())


app = FastAPI(title="CAN AI Diagnostic Backend", version="2.0.0")
generator = MockSignals()
engine = VehicleAIDiagnosticEngine(contamination=0.01, n_clusters=5, random_state=42)
_vehicle_tick = 0  # rotates CAN ID domain each call so ML sees a realistic multi-ID bus
explainer = LLMExplainer(model="gpt-5.4-mini")
feedback_store = FeedbackStore(Path("data") / "anomaly_feedback.jsonl")
cache = AnalyzeCache()

start_time = time.time()
metrics = {
    "requests_total": 0,
    "analyze_requests_total": 0,
    "analyzed_rows_total": 0,
    "anomalies_total": 0,
    "analyze_latency_total_ms": 0.0,
}
runtime_engine = RealtimeEngine()
runtime_stats = IDSStatistics(Path("live_runtime"))
live_signals_buffer: list[dict[str, Any]] = []
live_alerts_buffer: list[dict[str, Any]] = []
runtime_lock = threading.Lock()
replay_process: Optional[subprocess.Popen[str]] = None
replay_start_time: Optional[float] = None
replay_status: dict[str, Any] = {"state": "idle", "input_path": "", "started_at": None}
replay_monitor_thread: Optional[threading.Thread] = None
replay_stdout: str = ""
replay_stderr: str = ""
simulator_status: dict[str, Any] = {"state": "idle", "last_output": ""}
runtime_settings: dict[str, Any] = {"replay_speed": 1.0, "alert_threshold": 0.55, "export_folder": "backend/ml/outputs"}
# 10k+ frames at ~6 fps needs ~29 min; give 30 min headroom
MAX_REPLAY_DURATION_SEC = 1800


def _drain_pipe(pipe: Any, buf: list) -> None:
    """Continuously drain a pipe into buf to prevent OS pipe-buffer deadlock."""
    try:
        for line in iter(pipe.readline, ""):
            buf.append(line)
    except Exception:
        pass


def monitor_replay_process():
    """Monitor the replay process and update status when it completes or timeout."""
    global replay_process, replay_status, replay_start_time, replay_stdout, replay_stderr
    if replay_process is None or replay_start_time is None:
        return

    stdout_buf: list = []
    stderr_buf: list = []
    t_out = threading.Thread(target=_drain_pipe, args=(replay_process.stdout, stdout_buf), daemon=True)
    t_err = threading.Thread(target=_drain_pipe, args=(replay_process.stderr, stderr_buf), daemon=True)
    t_out.start()
    t_err.start()

    logger.info("[MONITOR] Starting process monitoring")
    try:
        while replay_process.poll() is None:
            # Check for timeout
            elapsed = time.time() - replay_start_time
            if elapsed > MAX_REPLAY_DURATION_SEC:
                logger.error(f"[MONITOR] Replay exceeded {MAX_REPLAY_DURATION_SEC}s timeout, terminating process")
                replay_process.terminate()
                try:
                    replay_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    logger.error("[MONITOR] Process did not terminate, killing it")
                    replay_process.kill()
                    replay_process.wait()
                
                # Capture output before returning
                if replay_process.stdout:
                    replay_stdout = replay_process.stdout.read()
                if replay_process.stderr:
                    replay_stderr = replay_process.stderr.read()
                
                replay_status.update({
                    "state": "error",
                    "error": "Replay timeout exceeded (120 seconds)",
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "elapsed_seconds": elapsed
                })
                logger.error("[MONITOR] Replay terminated due to timeout")
                return
            
            time.sleep(0.1)  # Poll every 100ms
            
        return_code = replay_process.returncode
        elapsed = time.time() - replay_start_time

        # Wait for background drain threads (pipes already continuously drained — no deadlock)
        t_out.join(timeout=3)
        t_err.join(timeout=3)
        replay_stdout = "".join(stdout_buf)
        replay_stderr = "".join(stderr_buf)
        if replay_stdout:
            logger.info(f"[MONITOR] Process stdout: {replay_stdout[:500]}")
        if replay_stderr:
            logger.error(f"[MONITOR] Process stderr: {replay_stderr[:500]}")
        
        logger.info(f"[MONITOR] Process completed with return code: {return_code} (elapsed: {elapsed:.2f}s)")
        
        # Update status based on return code
        if return_code == 0:
            replay_status.update({
                "state": "completed",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "return_code": return_code,
                "elapsed_seconds": elapsed,
                "results_ready": True
            })
            logger.info("[MONITOR] Status updated to completed")
        else:
            error_msg = f"Process exited with code {return_code}"
            if replay_stderr:
                error_msg += f"\n{replay_stderr[:200]}"
            replay_status.update({
                "state": "error", 
                "error": error_msg,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "return_code": return_code,
                "elapsed_seconds": elapsed
            })
            logger.error(f"[MONITOR] Process failed with code {return_code}\nStderr: {replay_stderr[:200]}")
            
    except Exception as e:
        logger.error(f"[MONITOR] Monitoring error: {e}")
        replay_status.update({
            "state": "error",
            "error": str(e),
            "completed_at": datetime.now(timezone.utc).isoformat()
        })
async def count_requests(request, call_next):  # type: ignore[no-untyped-def]
    metrics["requests_total"] += 1
    return await call_next(request)


@app.exception_handler(Exception)
async def global_exception_handler(_, exc: Exception):  # type: ignore[no-untyped-def]
    logger.exception("Unhandled API error: %s", exc)
    payload = ErrorResponse(error="internal_error", detail=str(exc))
    return JSONResponse(status_code=500, content=payload.model_dump())


@app.on_event("startup")
def startup_event() -> None:
    assets_root = Path("assets") / "EV-CANlogs-main"
    seed_df, seed_stats = collect_can_logs_from_assets(assets_root)
    logger.info("Seed collection stats: %s", seed_stats)
    if seed_df.empty:
        logger.warning("No seed data parsed from %s", assets_root)
        return
    prepared = FeatureEngineer.build(seed_df)
    if prepared.empty:
        logger.warning("Feature engineering produced empty training dataset")
        return
    engine.fit(prepared, auto_clusters=True)
    logger.info("Startup training complete: rows=%d clusters=%d", len(prepared), engine.model_bundle.n_clusters if engine.model_bundle else -1)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service="can-ai-diagnostic-backend",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@app.get("/vehicle")
def vehicle_snapshot() -> dict[str, Any]:
    global _vehicle_tick
    snapshot = generator.generate()
    ts = time.time()

    # Rotate through 4 CAN signal domains so the ML sees a realistic multi-ID bus.
    # Each domain encodes real snapshot fields into proper byte values.
    _vehicle_tick = (_vehicle_tick + 1) % 4
    if _vehicle_tick == 0:
        # Battery domain: voltage (scaled ×10, 2 bytes), SOC (×2, 1 byte), temp (offset +40 ×2, 1 byte)
        can_id = 0x1A2
        v = int(snapshot.get("BatteryVoltage", 395.0) * 10)
        b0, b1 = (v >> 8) & 0xFF, v & 0xFF
        b2 = int(snapshot.get("SOC", 78.0) * 2) & 0xFF
        b3 = int((snapshot.get("BatteryTemp", 31.0) + 40.0) * 2) & 0xFF
        payload = (b0, b1, b2, b3, 0, 0, 0, 0)
    elif _vehicle_tick == 1:
        # Motor domain: RPM (2 bytes), motor temp (offset +40, 1 byte), torque (×2, 1 byte)
        can_id = 0x3F1
        rpm = int(snapshot.get("MotorRPM", 3100))
        b0, b1 = (rpm >> 8) & 0xFF, rpm & 0xFF
        b2 = int((snapshot.get("MotorTemp", 48.0) + 40.0)) & 0xFF
        b3 = int(snapshot.get("MotorTorque", 120.0) * 2) & 0xFF
        payload = (b0, b1, b2, b3, 0, 0, 0, 0)
    elif _vehicle_tick == 2:
        # Chassis domain: speed (×100, 2 bytes), brake pedal (×10, 1 byte), accelerator (×2, 1 byte)
        can_id = 0x5D2
        spd = int(snapshot.get("VehicleSpeed", 60.0) * 100)
        b0, b1 = (spd >> 8) & 0xFF, spd & 0xFF
        b2 = int(snapshot.get("BrakePedal", 0.0) * 10) & 0xFF
        b3 = int(snapshot.get("AcceleratorPedal", 18.0) * 2) & 0xFF
        payload = (b0, b1, b2, b3, 0, 0, 0, 0)
    else:
        # Thermal domain: inverter temp (offset +40, 1 byte), cooling pump speed (1 byte), cell diff (×1000, 1 byte)
        can_id = 0x6E7
        b0 = int((snapshot.get("InverterTemp", 42.0) + 40.0)) & 0xFF
        b1 = int(snapshot.get("CoolingPumpSpeed", 20)) & 0xFF
        b2 = int(snapshot.get("CellVoltageDiff", 0.05) * 1000) & 0xFF
        b3 = int(snapshot.get("BatteryCoolingState", 0)) & 0xFF
        payload = (b0, b1, b2, b3, 0, 0, 0, 0)

    out = runtime_engine.process_frame(CanFrame(timestamp=ts, can_id=can_id, payload=payload))
    runtime_stats.on_frame()
    runtime_stats.on_score(float(out["score"]["fusion_score"]))
    signal_item = {
        "timestamp": ts,
        "can_id": _to_hex(can_id),
        "b0": payload[0], "b1": payload[1], "b2": payload[2], "b3": payload[3],
        "b4": payload[4], "b5": payload[5], "b6": payload[6], "b7": payload[7],
        "anomaly_score": float(out["score"]["fusion_score"]),
        "severity": str(out["score"]["risk_level"]),
    }
    with runtime_lock:
        live_signals_buffer.append(signal_item)
        if len(live_signals_buffer) > 2000:
            del live_signals_buffer[:-2000]
        if out["alert"] is not None:
            runtime_stats.on_alert(out["alert"])
            alert = out["alert"]
            live_alerts_buffer.append(
                {
                    "timestamp": float(alert.get("timestamp", ts)),
                    "severity": str(alert.get("risk_level", "UNKNOWN")),
                    "attack_type": "runtime",
                    "can_id": _to_hex(int(alert.get("can_id", 0))),
                    "score": float(alert.get("score", 0.0)),
                    "dominant_detection_layer": _dominant_layer(str(alert.get("reason", ""))),
                    "reason": str(alert.get("reason", "")),
                    "replay_source": "live",
                }
            )
            if len(live_alerts_buffer) > 2000:
                del live_alerts_buffer[:-2000]
    response_payload = {
        **snapshot,
        "source": "python-api",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "anomaly_score": float(out["score"]["fusion_score"]),
        "live_fps": float(runtime_stats.as_dict().get("fps", 0.0)),
        "live_can_id": int(can_id),
    }
    response_payload["battery"] = int(round(snapshot.get("SOC", 0)))
    response_payload["temperature"] = int(round(snapshot.get("BatteryTemp", 0.0)))
    response_payload["motor_status"] = "OK" if not any(
        [
            snapshot.get("OverheatFault"),
            snapshot.get("OverCurrentFault"),
            snapshot.get("UnderVoltageFault"),
            snapshot.get("BMSFault"),
            snapshot.get("MotorFault"),
        ]
    ) else "DEGRADED"
    return response_payload


@app.get("/metrics", response_model=MetricsResponse)
def get_metrics() -> MetricsResponse:
    analyze_count = max(metrics["analyze_requests_total"], 1)
    avg_latency = metrics["analyze_latency_total_ms"] / analyze_count
    clusters = engine.model_bundle.n_clusters if engine.model_bundle else 0
    return MetricsResponse(
        status="ok",
        uptime_seconds=round(time.time() - start_time, 3),
        requests_total=int(metrics["requests_total"]),
        analyze_requests_total=int(metrics["analyze_requests_total"]),
        analyzed_rows_total=int(metrics["analyzed_rows_total"]),
        anomalies_total=int(metrics["anomalies_total"]),
        avg_analyze_latency_ms=round(float(avg_latency), 3),
        model_loaded=engine.model_bundle is not None,
        model_clusters=int(clusters),
    )


@app.post(
    "/analyze",
    response_model=AnalyzeResponse,
    responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},

)
async def analyze(files: List[UploadFile] = File(...))  -> AnalyzeResponse:
    started = time.perf_counter()
    metrics["analyze_requests_total"] += 1
    if not files:
        raise HTTPException(status_code=400, detail="At least one CAN log file is required.")

    frames: list[pd.DataFrame] = []
    parse_total = 0
    parse_parsed = 0
    parse_skipped = 0

    for uploaded in files:
        try:
            raw = await uploaded.read()
        except Exception as exc:
            logger.warning("Failed reading upload %s: %s", uploaded.filename, exc)
            continue

        if not raw:
            continue

        fkey = cache.fingerprint(raw)
        cached = cache.get(fkey)
        if cached and "frame" in cached:
            frames.append(cached["frame"])
            continue

        text_stream = io.StringIO(raw.decode("utf-8", errors="ignore"))
        logger.info("Processing file: %s", uploaded.filename)
        parsed, stats = CanLogParser.parse_stream(text_stream, source_name=uploaded.filename or "uploaded.log")
        parse_total += stats.lines_total
        parse_parsed += stats.lines_parsed
        parse_skipped += stats.lines_skipped

        if not parsed.empty:
            frames.append(parsed)
            cache.set(fkey, {"frame": parsed})

    if not frames:
        raise HTTPException(
            status_code=400,
            detail="No valid CAN lines found. Expected patterns like '(timestamp) interface CAN_ID#DATA'.",
        )

    unified = pd.concat(frames, ignore_index=True)
    featured = FeatureEngineer.build(unified)
    predicted = engine.predict(featured)
    contexts = engine.build_anomaly_context(predicted)

    explained_results: list[AnalyzeResult] = []
    for context in contexts:
        explanation = explainer.explain(context)
        explained_results.append(AnalyzeResult(context=context, explanation=explanation))

    elapsed_ms = (time.perf_counter() - started) * 1000.0
    metrics["analyze_latency_total_ms"] += elapsed_ms
    metrics["analyzed_rows_total"] += int(len(unified))
    metrics["anomalies_total"] += int((predicted["anomaly"] == -1).sum())

    summary = AnalyzeSummary(
        files_received=len(files),
        rows_parsed=int(len(unified)),
        anomaly_count=int((predicted["anomaly"] == -1).sum()),
        normal_count=int((predicted["anomaly"] == 1).sum()),
        cluster_count=int(predicted["cluster"].nunique()) if len(predicted) else 0,
        parse_lines_total=int(parse_total),
        parse_lines_parsed=int(parse_parsed),
        parse_lines_skipped=int(parse_skipped),
        elapsed_ms=round(elapsed_ms, 3),
    )
    return AnalyzeResponse(summary=summary, anomalies=explained_results)


@app.post("/feedback", response_model=FeedbackResponse, responses={400: {"model": ErrorResponse}})
def submit_feedback(item: FeedbackItem) -> FeedbackResponse:
    feedback_store.append(
        {
            "can_id": item.can_id,
            "timestamp": item.timestamp,
            "label": item.label,
            "notes": item.notes,
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    return FeedbackResponse(status="saved")


@app.post("/infer", response_model=InferResponse)
def infer_frame(req: InferRequest) -> InferResponse:
    """Per-frame ML inference.

    Accepts a raw CAN frame (timestamp + can_id + 8 bytes) and runs it through
    the same RealtimeEngine used by live monitoring and replay analysis.
    Returns fusion_score, risk classification, and vehicle state.
    """
    ts = req.timestamp if req.timestamp > 0.0 else time.time()
    payload_tuple = (req.b0, req.b1, req.b2, req.b3, req.b4, req.b5, req.b6, req.b7)

    with runtime_lock:
        out = runtime_engine.process_frame(
            CanFrame(timestamp=ts, can_id=req.can_id, payload=payload_tuple)
        )

    score = float(out["score"]["fusion_score"])
    risk_level = str(out["score"]["risk_level"])
    vehicle_state = str(out.get("vehicle_state", "unknown"))
    label = "anomaly" if score >= runtime_engine.cfg.alert_threshold else "normal"

    return InferResponse(
        anomaly_score=score,
        anomaly_label=label,
        severity=risk_level,
        vehicle_state=vehicle_state,
    )


def _load_validation_csv(input_path: Path) -> pd.DataFrame:
    """Load a validation replay CSV.

    Handles two formats:
      1. Headerless (replay CSVs):  timestamp,can_id,b0..b7  — no header row
      2. Headered (generic CSVs):   first row is column names

    CAN-IDs may be decimal integers or hexadecimal strings (e.g. '02a0', '0x1A2').
    Byte columns may be decimal or hexadecimal strings.
    """
    # Sniff: if the first field of the first row parses as a float it is data, not a header.
    with open(input_path, "r", encoding="utf-8", errors="ignore") as fh:
        first_line = fh.readline().strip()

    first_field = first_line.split(",")[0].strip()
    try:
        float(first_field)
        is_headerless = True
    except ValueError:
        is_headerless = False

    col_names = ["timestamp", "can_id", "b0", "b1", "b2", "b3", "b4", "b5", "b6", "b7"]

    if is_headerless:
        df = pd.read_csv(
            input_path,
            header=None,
            names=col_names,
            low_memory=False,
        )
    else:
        df = pd.read_csv(input_path, low_memory=False)
        # Rename columns to canonical names if needed (best-effort)
        df.columns = [c.strip().lower() for c in df.columns]
        for i, name in enumerate(col_names):
            if name not in df.columns and i < len(df.columns):
                df.rename(columns={df.columns[i]: name}, inplace=True)

    # --- Parse CAN-ID (hex string or int) ---
    def _parse_can_id(val: object) -> int:
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return 0
        s = str(val).strip().lower()
        if s.startswith("0x"):
            return int(s, 16)
        try:
            return int(s, 16)       # try hex first (covers '02a0', '7fd', etc.)
        except ValueError:
            try:
                return int(float(s))
            except (ValueError, OverflowError):
                return 0

    # --- Parse byte value (hex string or int) ---
    def _parse_byte(val: object) -> int:
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return 0
        s = str(val).strip().lower()
        if s.startswith("0x"):
            return int(s, 16) & 0xFF
        try:
            return int(s, 16) & 0xFF    # hex (covers 'e3', 'a0', etc.)
        except ValueError:
            try:
                return int(float(s)) & 0xFF
            except (ValueError, OverflowError):
                return 0

    df["can_id"] = df["can_id"].apply(_parse_can_id)
    for col in ["b0", "b1", "b2", "b3", "b4", "b5", "b6", "b7"]:
        if col in df.columns:
            df[col] = df[col].apply(_parse_byte)
        else:
            df[col] = 0

    df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce").fillna(0.0)
    return df


@app.post("/api/validation/score_file", response_model=ValidationScoreResponse)
def api_validation_score_file(req: ValidationScoreRequest) -> ValidationScoreResponse:
    """Batch ML scoring for Validation Lab.

    Runs every frame in the given CSV file through a fresh RealtimeEngine
    (isolated from live traffic state) and returns per-frame scores.
    The engine is stateful — processes frames in chronological order,
    exactly as replay_runner.py does.
    """
    input_path = Path(req.input_path)
    if not input_path.exists():
        raise HTTPException(status_code=400, detail=f"File not found: {input_path}")

    try:
        df = _load_validation_csv(input_path)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to read CSV: {exc}")

    if df.empty:
        logger.info("[VAL_SCORE] %s — empty after load", input_path.name)
        return ValidationScoreResponse(status="ok", frame_count=0, anomaly_count=0, frames=[])

    if req.limit and req.limit > 0:
        df = df.iloc[: req.limit]

    unique_can_ids = sorted(df["can_id"].unique().tolist())
    logger.info(
        "[VAL_SCORE] %s — frames_loaded=%d  unique_can_ids=%d  ids=%s",
        input_path.name,
        len(df),
        len(unique_can_ids),
        unique_can_ids[:20],
    )

    # Fresh engine with calibrated validation weights.
    # timing_weight raised (0.35->0.60) to make DoS/flooding dominant signal.
    # payload_weight lowered (0.35->0.10) to suppress FPs from normal high-continuity payloads.
    # low_threshold raised (0.30->0.55) to match calibrated score distribution.
    val_engine = RealtimeEngine(VALIDATION_CONFIG)
    low_threshold = val_engine.cfg.low_threshold

    records = df.to_dict("records")
    frames_out: list[ValidationFrameScore] = []
    anomaly_count = 0

    for record in records:
        ts     = float(record["timestamp"])
        can_id = int(record["can_id"])
        payload = tuple(int(record[f"b{i}"]) & 0xFF for i in range(8))

        out = val_engine.process_frame(CanFrame(timestamp=ts, can_id=can_id, payload=payload))
        score     = float(out["score"]["fusion_score"])
        risk_level = str(out["score"]["risk_level"])

        label = "anomaly" if score >= low_threshold else "normal"
        if label == "anomaly":
            anomaly_count += 1

        frames_out.append(
            ValidationFrameScore(
                timestamp=ts,
                can_id=can_id,
                score=score,
                label=label,
                severity=risk_level,
            )
        )

    logger.info(
        "[VAL_SCORE] %s — frames_scored=%d  above_low_threshold(%.2f)=%d",
        input_path.name,
        len(frames_out),
        low_threshold,
        anomaly_count,
    )

    return ValidationScoreResponse(
        status="ok",
        frame_count=len(frames_out),
        anomaly_count=anomaly_count,
        frames=frames_out,
    )


def _to_hex(can_id: int) -> str:
    return f"0x{int(can_id):03X}"


def _dominant_layer(reason: str) -> str:
    vals: dict[str, float] = {}
    for part in str(reason).split(","):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        try:
            vals[k.strip()] = float(v.strip())
        except ValueError:
            continue
    if not vals:
        return "unknown"
    dom = max(vals, key=vals.get)
    mapping = {"timing": "timing", "payload": "payload", "ml": "ml", "persistence": "temporal"}
    return mapping.get(dom, dom)


@app.post("/api/live/start")
def api_live_start() -> dict[str, Any]:
    """Reset live session: clear buffers and IDS per-ID state so the new session starts clean."""
    with runtime_lock:
        live_signals_buffer.clear()
        live_alerts_buffer.clear()
    runtime_engine.state.reset()
    runtime_stats.reset()
    return {"status": "ok", "session_started_at": datetime.now(timezone.utc).isoformat()}


@app.post("/api/live/stop")
def api_live_stop() -> dict[str, Any]:
    """Return a summary of the current live session."""
    d = runtime_stats.as_dict()
    with runtime_lock:
        total_frames = len(live_signals_buffer)
        total_alerts = len(live_alerts_buffer)
    return {
        "status": "ok",
        "session_stopped_at": datetime.now(timezone.utc).isoformat(),
        "total_frames_buffered": total_frames,
        "total_alerts": total_alerts,
        "fps": d.get("fps", 0.0),
        "peak_score": d.get("max_fusion_score_observed", 0.0),
    }


@app.get("/api/live/signals")
def api_live_signals(limit: int = 200) -> dict[str, Any]:
    with runtime_lock:
        return {"status": "ok", "items": live_signals_buffer[-max(1, min(limit, 1000)):]}


@app.get("/api/live/alerts")
def api_live_alerts(limit: int = 200) -> dict[str, Any]:
    with runtime_lock:
        return {"status": "ok", "items": live_alerts_buffer[-max(1, min(limit, 1000)):]}


_explain_cache: dict[str, dict[str, Any]] = {}


def _parse_layer_values(reason: str) -> dict[str, float]:
    vals: dict[str, float] = {}
    for part in str(reason).split(","):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        try:
            vals[k.strip().lower()] = float(v.strip())
        except ValueError:
            continue
    return vals


@app.get("/api/explain/{alert_index}")
def api_explain_alert(alert_index: int) -> dict[str, Any]:
    """Return an AI-generated explanation for a live alert by its buffer index (0 = newest)."""
    with runtime_lock:
        if not live_alerts_buffer:
            raise HTTPException(status_code=404, detail="No alerts in buffer.")
        idx = max(0, min(alert_index, len(live_alerts_buffer) - 1))
        alert = dict(live_alerts_buffer[-(idx + 1)])  # newest-first indexing

    cache_key = f"{alert.get('can_id','')}-{alert.get('score',0):.4f}-{alert.get('reason','')}"
    if cache_key in _explain_cache:
        cached = _explain_cache[cache_key]
        layers = _parse_layer_values(str(alert.get("reason", "")))
        return {
            "status": "ok",
            "alert_index": idx,
            "cached": True,
            "layer_timing":   layers.get("timing", 0.0),
            "layer_payload":  layers.get("payload", 0.0),
            "layer_ml":       layers.get("ml", 0.0),
            "layer_temporal": layers.get("persistence", 0.0),
            **cached,
        }

    explanation = explainer.explain_alert(alert)
    _explain_cache[cache_key] = explanation
    layers = _parse_layer_values(str(alert.get("reason", "")))

    return {
        "status": "ok",
        "alert_index": idx,
        "cached": False,
        "summary":         explanation.get("summary", ""),
        "detail":          explanation.get("detail", ""),
        "recommendation":  explanation.get("recommendation", ""),
        "layer_timing":    layers.get("timing", 0.0),
        "layer_payload":   layers.get("payload", 0.0),
        "layer_ml":        layers.get("ml", 0.0),
        "layer_temporal":  layers.get("persistence", 0.0),
    }


@app.get("/api/live/status")
def api_live_status() -> dict[str, Any]:
    d = runtime_stats.as_dict()
    return {
        "status": "ok",
        "runtime_status": "running",
        "connection_status": "connected",
        "packet_rate": d.get("fps", 0.0),
        "latency_ms": max(0.1, 1000.0 / max(float(d.get("fps", 0.001)), 0.001)),
        "dropped_frames": 0,
        "active_can_ids": len(d.get("alerts_per_can_id", {})),
    }


@app.get("/api/runtime/statistics")
def api_runtime_statistics() -> dict[str, Any]:
    d = runtime_stats.as_dict()
    return {"status": "ok", "statistics": d}


@app.get("/api/runtime/health")
def api_runtime_health() -> dict[str, Any]:
    return {
        "status": "ok",
        "runtime_engine_state": "running",
        "model_loaded": True,
        "alert_threshold": runtime_settings["alert_threshold"],
        "replay_engine_state": replay_status["state"],
        "simulator_state": simulator_status["state"],
    }


@app.post("/api/replay/start")
def api_replay_start(req: ReplayStartRequest) -> dict[str, Any]:
    global replay_process, replay_monitor_thread, replay_start_time, replay_stdout, replay_stderr
    input_path = Path(req.input_path)
    if not input_path.exists():
        raise HTTPException(status_code=400, detail=f"Replay input file not found: {input_path}")
    if replay_process is not None and replay_process.poll() is None:
        raise HTTPException(status_code=409, detail="Replay already running.")

    logger.info(f"[REPLAY] Starting replay for {input_path}")
    cmd = [sys.executable, "-m", "backend.ml.runtime.replay_runner", "--input", str(input_path)]
    if req.limit > 0:
        cmd.extend(["--limit", str(req.limit)])
    
    logger.info(f"[REPLAY] Command: {' '.join(cmd)}")
    # Capture stdout and stderr to pipes so we can see errors
    # Run from the project root directory so relative paths work correctly
    project_root = Path(__file__).resolve().parents[2]
    replay_process = subprocess.Popen(
        cmd, 
        stdout=subprocess.PIPE, 
        stderr=subprocess.PIPE, 
        text=True,
        cwd=str(project_root)
    )
    replay_start_time = time.time()
    replay_stdout = ""
    replay_stderr = ""
    logger.info(f"[REPLAY] Process started with PID: {replay_process.pid} in {project_root}")
    
    # Start monitoring thread
    replay_monitor_thread = threading.Thread(target=monitor_replay_process, daemon=True)
    replay_monitor_thread.start()
    logger.info("[REPLAY] Monitoring thread started")
    
    replay_status.update({
        "state": "running", 
        "input_path": str(input_path), 
        "started_at": datetime.now(timezone.utc).isoformat(),
        "frames_processed": 0,
        "total_frames": None
    })
    logger.info("[REPLAY] Status set to running")
    return {"status": "ok", "message": "replay started", "input_path": str(input_path)}


@app.post("/api/replay/stop")
def api_replay_stop() -> dict[str, Any]:
    global replay_process, replay_monitor_thread
    if replay_process is not None and replay_process.poll() is None:
        logger.info("[REPLAY] Stopping replay process")
        replay_process.terminate()
        replay_status["state"] = "stopped"
        replay_status["stopped_at"] = datetime.now(timezone.utc).isoformat()
        # Wait for monitoring thread to finish
        if replay_monitor_thread and replay_monitor_thread.is_alive():
            replay_monitor_thread.join(timeout=5.0)
        return {"status": "ok", "message": "replay stopped"}
    return {"status": "ok", "message": "no active replay"}


@app.get("/api/replay/status")
def api_replay_status() -> dict[str, Any]:
    global replay_process
    state = replay_status.get("state", "idle")
    
    # If we think it's running, double-check the process
    if state == "running":
        if replay_process is None or replay_process.poll() is not None:
            # Process completed, but monitoring thread should have updated status
            # This is a fallback in case monitoring failed
            if replay_process and replay_process.poll() == 0:
                state = "completed"
                replay_status["state"] = state
                replay_status["completed_at"] = datetime.now(timezone.utc).isoformat()
                logger.warning("[REPLAY] Status fallback: process completed but monitoring missed it")
            elif replay_process and replay_process.poll() != 0:
                state = "error"
                replay_status["state"] = state
                replay_status["error"] = f"Process exited with code {replay_process.poll()}"
                replay_status["completed_at"] = datetime.now(timezone.utc).isoformat()
                logger.error(f"[REPLAY] Status fallback: process failed with code {replay_process.poll()}")
    
    # Calculate elapsed time if running
    elapsed = None
    if replay_status.get("started_at"):
        start_time = datetime.fromisoformat(replay_status["started_at"])
        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
    
    response = {
        "status": "ok",
        "state": state,
        "input_path": replay_status.get("input_path", ""),
        "started_at": replay_status.get("started_at"),
        "completed_at": replay_status.get("completed_at"),
        "elapsed_seconds": elapsed,
        "frames_processed": replay_status.get("frames_processed", 0),
        "total_frames": replay_status.get("total_frames"),
        "results_ready": state == "completed"
    }
    
    if "error" in replay_status:
        response["error"] = replay_status["error"]
    
    return response


@app.get("/api/replay/results")
def api_replay_results() -> dict[str, Any]:
    files = sorted(glob.glob("backend/ml/outputs/validation_reports/*_summary.json"), key=os.path.getmtime, reverse=True)
    if not files:
        return {"status": "ok", "result": None}
    latest = files[0]
    payload = json.loads(Path(latest).read_text(encoding="utf-8"))
    return {"status": "ok", "path": latest, "result": payload}


@app.get("/api/replay/alerts")
def api_replay_alerts(limit: int = 500) -> dict[str, Any]:
    """Return per-alert records from the most recent replay summary JSON."""
    files = sorted(glob.glob("backend/ml/outputs/validation_reports/*_summary.json"), key=os.path.getmtime, reverse=True)
    if not files:
        return {"status": "ok", "items": []}
    payload = json.loads(Path(files[0]).read_text(encoding="utf-8"))
    records = payload.get("alert_records", [])[:max(1, min(limit, 1000))]

    def _reason_bucket(reason_text: str) -> str:
        vals: dict[str, float] = {}
        for part in reason_text.split(","):
            if "=" not in part:
                continue
            k, v = part.split("=", 1)
            try:
                vals[k.strip()] = float(v.strip())
            except ValueError:
                continue
        if not vals:
            return "unknown"
        dominant = max(vals, key=lambda key: vals[key])
        return {"timing": "timing_burst", "payload": "continuity_break", "ml": "ml_outlier"}.get(dominant, dominant)

    items = []
    for r in records:
        reason_text = str(r.get("reason", ""))
        reason = _reason_bucket(reason_text)
        can_id = int(r.get("can_id", 0))
        items.append({
            "timestamp": float(r.get("timestamp", 0.0)),
            "severity": str(r.get("risk_level", "LOW")),
            "attack_type": str(r.get("risk_level", "LOW")),
            "can_id": f"0x{can_id:X}",
            "score": float(r.get("score", 0.0)),
            "dominant_detection_layer": reason,          # bucketed label for display
            "reason": str(r.get("reason", "")),           # original long-format for layer parsing
        })
    return {"status": "ok", "items": items}


_PARTIAL_ALERTS_PATH = Path("backend/ml/outputs/validation_reports/partial_alerts.json")

@app.get("/api/replay/partial-alerts")
def api_replay_partial_alerts() -> dict[str, Any]:
    """Return partial per-alert records written by replay_runner every ~1000 frames."""
    if not _PARTIAL_ALERTS_PATH.exists():
        return {"status": "ok", "items": []}
    try:
        records = json.loads(_PARTIAL_ALERTS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"status": "ok", "items": []}

    def _reason_bucket(reason_text: str) -> str:
        vals: dict[str, float] = {}
        for part in reason_text.split(","):
            if "=" not in part:
                continue
            k, v = part.split("=", 1)
            try:
                vals[k.strip()] = float(v.strip())
            except ValueError:
                continue
        if not vals:
            return "unknown"
        dominant = max(vals, key=lambda key: vals[key])
        return {"timing": "timing_burst", "payload": "continuity_break", "ml": "ml_outlier"}.get(dominant, dominant)

    items = []
    for r in records:
        reason_text = str(r.get("reason", ""))
        can_id = int(r.get("can_id", 0))
        items.append({
            "timestamp": float(r.get("timestamp", 0.0)),
            "severity": str(r.get("risk_level", "LOW")),
            "attack_type": str(r.get("risk_level", "LOW")),
            "can_id": f"0x{can_id:X}",
            "score": float(r.get("score", 0.0)),
            "dominant_detection_layer": _reason_bucket(reason_text),
            "reason": reason_text,
        })
    return {"status": "ok", "items": items}


@app.post("/api/simulator/generate")
def api_simulator_generate(req: SimulatorGenerateRequest) -> dict[str, Any]:
    output_path = Path(req.output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    simulator_status["state"] = "running"
    cmd = [
        sys.executable, "-m", "backend.ml.simulator.traffic_generator",
        "--frames", str(req.frames),
        "--attack", req.attack,
        "--intensity", str(req.intensity),
        "--out", str(output_path),
    ]
    subprocess.run(cmd, check=True)
    simulator_status["state"] = "idle"
    simulator_status["last_output"] = str(output_path)
    return {"status": "ok", "output_path": str(output_path), "attack": req.attack, "frames": req.frames, "intensity": req.intensity}


@app.get("/api/simulator/attacks")
def api_simulator_attacks() -> dict[str, Any]:
    return {"status": "ok", "attacks": ["normal", "fuzzy", "dos", "rpm", "gear"]}


@app.get("/api/validation/reports")
def api_validation_reports() -> dict[str, Any]:
    paths = sorted(glob.glob("backend/ml/outputs/validation_reports/*.json"), key=os.path.getmtime, reverse=True)
    return {"status": "ok", "reports": paths[:50]}


@app.get("/api/system/info")
def api_system_info() -> dict[str, Any]:
    return {
        "status": "ok",
        "fastapi_status": "ok",
        "runtime_engine_state": "running",
        "replay_engine_state": replay_status.get("state", "idle"),
        "simulator_state": simulator_status.get("state", "idle"),
    }


@app.get("/api/settings")
def api_settings_get() -> dict[str, Any]:
    return {"status": "ok", "settings": runtime_settings}


@app.post("/api/settings")
def api_settings_set(payload: dict[str, Any]) -> dict[str, Any]:
    if "replay_speed" in payload:
        runtime_settings["replay_speed"] = max(0.1, min(float(payload["replay_speed"]), 8.0))
    if "alert_threshold" in payload:
        val = max(0.0, min(float(payload["alert_threshold"]), 1.0))
        runtime_settings["alert_threshold"] = val
        runtime_engine.cfg.alert_threshold = val
    if "export_folder" in payload:
        runtime_settings["export_folder"] = str(payload["export_folder"])
    return {"status": "ok", "settings": runtime_settings}


if __name__ == "__main__":
    uvicorn.run("backend.api.server:app", host="127.0.0.1", port=8765, reload=False)
