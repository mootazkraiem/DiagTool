"""Offline session analyzer.

Full pipeline: file → raw frames → DBC decode → ML anomaly scoring → session JSON.

Supports:
  .MF4  → asammdf
  .asc  → Vector ASC parser
  .log  → candump (socketCAN) parser
  .txt  → PCAN text parser or candump
  .csv  → SavvyCAN CSV or generic timestamp/can_id/b0-b7
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterator

import pandas as pd

from backend.decoding.dbc_manager import get_manager as get_dbc_manager
from backend.decoding.vehicle_profiles import get as get_profile
from backend.ml.runtime.realtime_engine import RealtimeEngine, CanFrame
from backend.ml.runtime.runtime_config import VALIDATION_CONFIG

logger = logging.getLogger(__name__)

_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "backend" / "ml" / "outputs" / "offline_sessions"
_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# In-memory session registry  {session_id → SessionState}
_sessions: dict[str, "SessionState"] = {}
_sessions_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class FrameRecord:
    timestamp: float
    can_id: int
    can_id_hex: str
    b0: int; b1: int; b2: int; b3: int
    b4: int; b5: int; b6: int; b7: int
    anomaly_score: float
    severity: str
    signals: list[dict]   # [{name, value, unit, out_of_range, system}]


@dataclass
class SessionState:
    session_id: str
    file_path: str
    vehicle_id: str
    status: str = "pending"       # pending | running | done | error
    progress: float = 0.0
    total_frames: int = 0
    processed_frames: int = 0
    anomaly_count: int = 0
    error: str = ""
    started_at: str = ""
    completed_at: str = ""
    output_path: str = ""
    frames: list[FrameRecord] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def start_analysis(file_path: str, vehicle_id: str) -> str:
    """Kick off background analysis. Returns session_id immediately."""
    session_id = uuid.uuid4().hex[:12]
    state = SessionState(
        session_id=session_id,
        file_path=file_path,
        vehicle_id=vehicle_id,
        started_at=_now(),
    )
    with _sessions_lock:
        _sessions[session_id] = state

    t = threading.Thread(target=_run, args=(session_id,), daemon=True)
    t.start()
    return session_id


def get_status(session_id: str) -> dict[str, Any] | None:
    with _sessions_lock:
        s = _sessions.get(session_id)
    if s is None:
        return None
    return {
        "session_id":       s.session_id,
        "status":           s.status,
        "progress":         round(s.progress, 1),
        "total_frames":     s.total_frames,
        "processed_frames": s.processed_frames,
        "anomaly_count":    s.anomaly_count,
        "error":            s.error,
        "started_at":       s.started_at,
        "completed_at":     s.completed_at,
        "output_path":      s.output_path,
        "vehicle_id":       s.vehicle_id,
        "file_path":        s.file_path,
    }


def get_frames(session_id: str, offset: int = 0, limit: int = 500) -> dict[str, Any] | None:
    with _sessions_lock:
        s = _sessions.get(session_id)
    if s is None:
        return None
    page = s.frames[offset: offset + limit]
    return {
        "session_id": session_id,
        "total":      len(s.frames),
        "offset":     offset,
        "limit":      limit,
        "frames":     [asdict(f) for f in page],
    }


def get_summary(session_id: str) -> dict[str, Any] | None:
    with _sessions_lock:
        s = _sessions.get(session_id)
    if s is None:
        return None
    if s.status != "done":
        return {"session_id": session_id, "status": s.status}

    # Top-5 CAN IDs by anomaly score
    from collections import defaultdict
    id_scores: dict[int, list[float]] = defaultdict(list)
    for f in s.frames:
        id_scores[f.can_id].append(f.anomaly_score)
    top_threats = sorted(
        [{"can_id": f"0x{cid:X}", "avg_score": round(sum(v)/len(v), 4), "count": len(v)}
         for cid, v in id_scores.items()],
        key=lambda x: -x["avg_score"]
    )[:5]

    # Signal inventory: unique signal names decoded
    seen_signals: set[str] = set()
    for f in s.frames:
        for sig in f.signals:
            seen_signals.add(sig["name"])

    return {
        "session_id":     s.session_id,
        "vehicle_id":     s.vehicle_id,
        "file_path":      s.file_path,
        "status":         s.status,
        "total_frames":   s.total_frames,
        "anomaly_count":  s.anomaly_count,
        "anomaly_rate":   round(s.anomaly_count / max(s.total_frames, 1) * 100, 2),
        "top_threats":    top_threats,
        "decoded_signals": sorted(seen_signals),
        "started_at":     s.started_at,
        "completed_at":   s.completed_at,
        "output_path":    s.output_path,
    }


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------

def _run(session_id: str) -> None:
    with _sessions_lock:
        s = _sessions[session_id]

    s.status = "running"
    path = Path(s.file_path)

    try:
        raw_frames = list(_load_file(path))
        s.total_frames = len(raw_frames)
        if s.total_frames == 0:
            raise ValueError("No frames extracted from file")

        engine = RealtimeEngine(VALIDATION_CONFIG, vehicle_id=s.vehicle_id)
        mgr = get_dbc_manager()
        records: list[FrameRecord] = []

        for i, (ts, can_id, payload) in enumerate(raw_frames):
            out = engine.process_frame(CanFrame(timestamp=ts, can_id=can_id, payload=payload))
            score = float(out["score"]["fusion_score"])
            severity = str(out["score"]["risk_level"])

            # DBC decode
            raw_signals = mgr.decode(s.vehicle_id, can_id, payload)
            signals = [
                {
                    "name":         sig.name,
                    "value":        sig.value,
                    "unit":         sig.unit,
                    "out_of_range": sig.out_of_range,
                    "system":       sig.system,
                }
                for sig in raw_signals
            ]

            rec = FrameRecord(
                timestamp=round(ts, 6),
                can_id=can_id,
                can_id_hex=f"0x{can_id:X}",
                b0=payload[0], b1=payload[1], b2=payload[2], b3=payload[3],
                b4=payload[4], b5=payload[5], b6=payload[6], b7=payload[7],
                anomaly_score=round(score, 4),
                severity=severity,
                signals=signals,
            )
            records.append(rec)

            if score >= engine.cfg.alert_threshold:
                s.anomaly_count += 1

            s.processed_frames = i + 1
            s.progress = (i + 1) / s.total_frames * 100

        s.frames = records

        # Write session JSON
        out_path = _OUTPUT_DIR / f"session_{session_id}.json"
        summary = {
            "session_id":    session_id,
            "vehicle_id":    s.vehicle_id,
            "file_path":     s.file_path,
            "total_frames":  s.total_frames,
            "anomaly_count": s.anomaly_count,
            "completed_at":  _now(),
            "frames":        [asdict(r) for r in records],
        }
        out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        s.output_path = str(out_path)
        s.status = "done"
        s.completed_at = _now()
        s.progress = 100.0
        logger.info("[OFFLINE] Session %s done — %d frames, %d anomalies", session_id, s.total_frames, s.anomaly_count)

    except Exception as exc:
        logger.exception("[OFFLINE] Session %s failed: %s", session_id, exc)
        s.status = "error"
        s.error = str(exc)
        s.completed_at = _now()


# ---------------------------------------------------------------------------
# Format-aware file loader
# ---------------------------------------------------------------------------

def _load_file(path: Path) -> Iterator[tuple[float, int, tuple]]:
    """Yield (timestamp, can_id, payload_tuple_8) for every frame in the file."""
    suffix = path.suffix.lower()

    if suffix == ".mf4":
        yield from _load_mf4(path)
    elif suffix == ".asc":
        yield from _load_asc(path)
    elif suffix in (".log",):
        yield from _load_candump(path)
    elif suffix == ".txt":
        # Try PCAN first, then candump
        yield from _load_pcan_or_candump(path)
    elif suffix == ".csv":
        yield from _load_csv(path)
    else:
        raise ValueError(f"Unsupported file format: {suffix}")


def _load_mf4(path: Path) -> Iterator[tuple[float, int, tuple]]:
    # Reuses the same multi-channel-group-aware extractor as the standalone MF4->CSV
    # converter (backend.data_processing.mf4_to_csv_converter) — a single
    # mdf.to_dataframe() call only surfaces the first CAN_DataFrame channel group,
    # silently dropping every frame recorded on additional bus channels/groups,
    # which is exactly where the real traffic lives in multi-bus CANedge loggers.
    from backend.data_processing.mf4_to_csv_converter import _extract_raw_rows

    for row, _corrected in _extract_raw_rows(path):
        ts, can_id, *bs = row
        yield float(ts), int(can_id), tuple(bs)


def _load_csv(path: Path) -> Iterator[tuple[float, int, tuple]]:
    df = pd.read_csv(path, low_memory=False)
    cols = [c.strip().lower() for c in df.columns]
    df.columns = cols

    # SavvyCAN format: Time Stamp, ID, Extended, Dir, Bus, LEN, D1..D8
    if "id" in cols and "d1" in cols:
        for _, row in df.iterrows():
            try:
                ts = float(row.get("time stamp", row.get("timestamp", 0))) / 1000.0
                can_id = int(str(row["id"]).strip(), 16)
                bs = tuple(int(str(row.get(f"d{i}", 0)).strip(), 16) & 0xFF for i in range(1, 9))
                yield ts, can_id, bs
            except Exception:
                continue
        return

    # Generic: timestamp, can_id, b0..b7
    if "can_id" in cols:
        byte_cols = [c for c in cols if c.startswith("b") and c[1:].isdigit()]
        byte_cols = sorted(byte_cols, key=lambda c: int(c[1:]))[:8]
        for _, row in df.iterrows():
            try:
                ts = float(row["timestamp"])
                can_id = int(str(row["can_id"]).strip(), 16) if str(row["can_id"]).strip().startswith(("0x", "0X")) else int(float(row["can_id"]))
                bs = tuple(int(float(row.get(c, 0))) & 0xFF for c in byte_cols)
                bs += (0,) * (8 - len(bs))
                yield ts, can_id, bs[:8]
            except Exception:
                continue


def _load_asc(path: Path) -> Iterator[tuple[float, int, tuple]]:
    """Vector ASC format: <timestamp> <channel> <CAN_ID> <Rx|Tx> d <DLC> <b0> <b1>..."""
    import re
    pattern = re.compile(
        r'^\s*(\d+\.\d+)\s+\d+\s+([0-9A-Fa-f]+)\s+\w+\s+d\s+\d+\s+((?:[0-9A-Fa-f]{2}\s*)+)'
    )
    with path.open("r", encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            m = pattern.match(line)
            if not m:
                continue
            try:
                ts = float(m.group(1))
                can_id = int(m.group(2), 16)
                bs = [int(b, 16) & 0xFF for b in m.group(3).split()][:8]
                bs += [0] * (8 - len(bs))
                yield ts, can_id, tuple(bs)
            except Exception:
                continue


def _load_candump(path: Path) -> Iterator[tuple[float, int, tuple]]:
    """candump format: (timestamp) interface CAN_ID#DATAHEX or [DLC] b0 b1..."""
    import re
    # Pattern 1: (1234.567) can0 1A2#DEADBEEF
    p1 = re.compile(r'\((\d+\.\d+)\)\s+\S+\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]*)')
    # Pattern 2: timestamp channel ID [DLC] b0 b1...
    p2 = re.compile(r'(\d+\.\d+)\s+\S+\s+([0-9A-Fa-f]+)\s+\[\d+\]\s+((?:[0-9A-Fa-f]{2}\s*)+)')
    with path.open("r", encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            m = p1.match(line)
            if m:
                try:
                    ts = float(m.group(1))
                    can_id = int(m.group(2), 16)
                    hex_data = m.group(3)
                    bs = [int(hex_data[i:i+2], 16) for i in range(0, min(len(hex_data), 16), 2)]
                    bs += [0] * (8 - len(bs))
                    yield ts, can_id, tuple(bs[:8])
                    continue
                except Exception:
                    pass
            m = p2.match(line)
            if m:
                try:
                    ts = float(m.group(1))
                    can_id = int(m.group(2), 16)
                    bs = [int(b, 16) & 0xFF for b in m.group(3).split()][:8]
                    bs += [0] * (8 - len(bs))
                    yield ts, can_id, tuple(bs)
                except Exception:
                    pass


def _load_pcan_or_candump(path: Path) -> Iterator[tuple[float, int, tuple]]:
    """Try PCAN text format first, fall back to candump."""
    import re
    # PCAN text: <timestamp>  <HEX_ID>  <DLC>  <b0> <b1>...
    pcan_pattern = re.compile(
        r'^\s*(\d+(?:\.\d+)?)\s+([0-9A-Fa-f]+)\s+(\d)\s+((?:[0-9A-Fa-f]{2}\s*)+)'
    )
    found_pcan = False
    with path.open("r", encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            m = pcan_pattern.match(line)
            if m:
                found_pcan = True
                break

    if found_pcan:
        with path.open("r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                m = pcan_pattern.match(line)
                if not m:
                    continue
                try:
                    ts = float(m.group(1)) / 1000.0  # ms → s
                    can_id = int(m.group(2), 16)
                    bs = [int(b, 16) & 0xFF for b in m.group(4).split()][:8]
                    bs += [0] * (8 - len(bs))
                    yield ts, can_id, tuple(bs)
                except Exception:
                    continue
    else:
        yield from _load_candump(path)


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
