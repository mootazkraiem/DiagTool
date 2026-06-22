from __future__ import annotations

import io
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List

import pandas as pd
import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from core.diagnostic_backend import (
    AnalyzeCache,
    CanLogParser,
    FeatureEngineer,
    FeedbackStore,
    LLMExplainer,
    VehicleAIDiagnosticEngine,
    collect_can_logs_from_assets,
)
from mocksignals import MockSignals


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
    context: dict[str, Any]
    explanation: dict[str, str]


class AnalyzeResponse(BaseModel):
    summary: AnalyzeSummary
    anomalies: list[AnalyzeResult]


app = FastAPI(title="CAN AI Diagnostic Backend", version="2.0.0")
generator = MockSignals()
engine = VehicleAIDiagnosticEngine(contamination=0.01, n_clusters=5, random_state=42)
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


@app.middleware("http")
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


@app.get("/vehicle", response_model=VehicleResponse)
def vehicle_snapshot() -> dict[str, Any]:
    snapshot = generator.generate()
    payload = {
        **snapshot,
        "source": "python-api",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    payload["battery"] = int(round(snapshot.get("SOC", 0)))
    payload["temperature"] = int(round(snapshot.get("BatteryTemp", 0.0)))
    payload["motor_status"] = "OK" if not any(
        [
            snapshot.get("OverheatFault"),
            snapshot.get("OverCurrentFault"),
            snapshot.get("UnderVoltageFault"),
            snapshot.get("BMSFault"),
            snapshot.get("MotorFault"),
        ]
    ) else "DEGRADED"
    return payload


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


if __name__ == "__main__":
    uvicorn.run("python_api_server:app", host="127.0.0.1", port=8765, reload=False)
