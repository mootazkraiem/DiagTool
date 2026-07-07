"""SQLite persistence layer for CANvision.

Stores live CAN frames and alert history across sessions, and triggers
incremental model retraining whenever enough new normal frames accumulate.

Database location: backend/db/canvision.db  (created automatically)

Tables
------
sessions       — one row per live/replay session
live_frames    — raw CAN frames with IDS label and optional user feedback
alert_history  — persisted alerts (survives app restart)

Retraining
----------
After every RETRAIN_THRESHOLD new normal frames the engine is asked to
retrain itself in a background thread using the stored frames.
"""
from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

import pandas as pd

_DB_PATH = Path(__file__).resolve().parent / "canvision.db"

RETRAIN_THRESHOLD = 10_000   # new normal frames before triggering retrain
_SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS sessions (
    id           TEXT PRIMARY KEY,
    started_at   REAL NOT NULL,
    ended_at     REAL,
    source       TEXT,          -- 'live' | 'replay' | 'inject'
    frame_count  INTEGER DEFAULT 0,
    anomaly_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS live_frames (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    timestamp   REAL NOT NULL,
    can_id      INTEGER NOT NULL,
    b0 INTEGER DEFAULT 0, b1 INTEGER DEFAULT 0,
    b2 INTEGER DEFAULT 0, b3 INTEGER DEFAULT 0,
    b4 INTEGER DEFAULT 0, b5 INTEGER DEFAULT 0,
    b6 INTEGER DEFAULT 0, b7 INTEGER DEFAULT 0,
    anomaly     INTEGER DEFAULT 1,   -- 1=normal, -1=anomalous (IDS output)
    user_label  TEXT,                -- NULL | 'normal' | 'attack'
    created_at  REAL DEFAULT (unixepoch())
);

CREATE INDEX IF NOT EXISTS idx_lf_session   ON live_frames(session_id);
CREATE INDEX IF NOT EXISTS idx_lf_can_id    ON live_frames(can_id);
CREATE INDEX IF NOT EXISTS idx_lf_timestamp ON live_frames(timestamp);
CREATE INDEX IF NOT EXISTS idx_lf_anomaly   ON live_frames(anomaly);

CREATE TABLE IF NOT EXISTS alert_history (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT NOT NULL,
    timestamp    REAL NOT NULL,
    can_id       TEXT NOT NULL,
    severity     TEXT NOT NULL,
    score        REAL NOT NULL,
    attack_type  TEXT,
    reason       TEXT,
    temporal_pattern TEXT,
    plausibility_passed INTEGER DEFAULT 1,
    timing_anomaly      INTEGER DEFAULT 0,
    recommended_response TEXT,
    created_at   REAL DEFAULT (unixepoch())
);

CREATE INDEX IF NOT EXISTS idx_ah_session  ON alert_history(session_id);
CREATE INDEX IF NOT EXISTS idx_ah_severity ON alert_history(severity);
"""


class CanStore:
    """Thread-safe SQLite store for CAN frames and alerts.

    Usage
    -----
    store = CanStore()
    sid = store.new_session(source="live")
    store.write_frames(sid, df)          # df from FeatureEngineer.build()
    store.write_alert(sid, ctx)          # ctx from build_anomaly_context()
    store.end_session(sid)
    """

    def __init__(self, db_path: Path = _DB_PATH, retrain_callback: Callable | None = None):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._retrain_cb = retrain_callback
        self._new_normal_since_retrain = 0
        self._init_db()

    # ── Init ──────────────────────────────────────────────────────────────────

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    # ── Sessions ──────────────────────────────────────────────────────────────

    def new_session(self, source: str = "live") -> str:
        sid = str(uuid.uuid4())[:16]
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO sessions(id, started_at, source) VALUES(?,?,?)",
                (sid, time.time(), source),
            )
        return sid

    def end_session(self, session_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE sessions SET ended_at=?, frame_count=(SELECT COUNT(*) FROM live_frames WHERE session_id=?),"
                " anomaly_count=(SELECT COUNT(*) FROM live_frames WHERE session_id=? AND anomaly=-1)"
                " WHERE id=?",
                (time.time(), session_id, session_id, session_id),
            )

    # ── Frame storage ─────────────────────────────────────────────────────────

    def write_frames(self, session_id: str, df: pd.DataFrame) -> int:
        """Bulk-insert frames from a DataFrame. Returns rows inserted."""
        if df.empty:
            return 0

        byte_col_names = ["b0","b1","b2","b3","b4","b5","b6","b7"]
        insert = pd.DataFrame()
        insert["timestamp"] = df["timestamp"].astype(float) if "timestamp" in df.columns else 0.0
        insert["can_id"]    = (
            pd.to_numeric(df["can_id"], errors="coerce").fillna(0).astype(int)
            if "can_id" in df.columns else 0
        )
        for c in byte_col_names:
            insert[c] = df[c].fillna(0).astype(int) if c in df.columns else 0
        insert["anomaly"] = df["anomaly"].astype(int) if "anomaly" in df.columns else 1
        rows = [(session_id, *t) for t in insert.itertuples(index=False, name=None)]

        sql = """INSERT INTO live_frames
                    (session_id, timestamp, can_id, b0,b1,b2,b3,b4,b5,b6,b7, anomaly)
                 VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"""

        should_retrain = False
        with self._lock, self._connect() as conn:
            conn.executemany(sql, rows)

            # Count new normal frames and maybe trigger retraining. Done under
            # the same lock as the insert so two concurrent writers can't both
            # observe a pre-reset counter and both fire the retrain callback.
            new_normal = sum(1 for r in rows if r[-1] == 1)
            self._new_normal_since_retrain += new_normal
            if self._new_normal_since_retrain >= RETRAIN_THRESHOLD and self._retrain_cb:
                self._new_normal_since_retrain = 0
                should_retrain = True

        if should_retrain:
            threading.Thread(target=self._retrain_cb, daemon=True).start()

        return len(rows)

    def write_alert(self, session_id: str, ctx: dict[str, Any]) -> None:
        """Persist one alert context dict."""
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO alert_history
                   (session_id, timestamp, can_id, severity, score, attack_type, reason,
                    temporal_pattern, plausibility_passed, timing_anomaly, recommended_response)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    session_id,
                    float(ctx.get("timestamp", 0.0)),
                    str(ctx.get("can_id", "unknown")),
                    str(ctx.get("severity", "WARNING")),
                    float(ctx.get("anomaly_score", 0.0)),
                    str(ctx.get("attack_type", "")),
                    str(ctx.get("reason", "")),
                    str(ctx.get("temporal_pattern", "normal")),
                    int(bool(ctx.get("plausibility_passed", True))),
                    int(bool(ctx.get("timing_anomaly", False))),
                    str(ctx.get("recommended_response", "")),
                ),
            )

    # ── Reads ─────────────────────────────────────────────────────────────────

    def load_normal_frames(self, limit: int = 50_000) -> pd.DataFrame:
        """Return the most recent normal frames for retraining."""
        sql = """
            SELECT timestamp, can_id, b0,b1,b2,b3,b4,b5,b6,b7
            FROM live_frames
            WHERE anomaly = 1
            ORDER BY id DESC
            LIMIT ?
        """
        with self._connect() as conn:
            return pd.read_sql_query(sql, conn, params=(limit,))

    def load_alert_history(self, limit: int = 500, session_id: str | None = None) -> list[dict]:
        """Return recent alerts as a list of dicts."""
        if session_id:
            sql = "SELECT * FROM alert_history WHERE session_id=? ORDER BY timestamp DESC LIMIT ?"
            params = (session_id, limit)
        else:
            sql = "SELECT * FROM alert_history ORDER BY timestamp DESC LIMIT ?"
            params = (limit,)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def session_stats(self, session_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT frame_count, anomaly_count FROM sessions WHERE id=?", (session_id,)
            ).fetchone()
        if row is None:
            return {}
        return {"frame_count": row[0], "anomaly_count": row[1]}

    def total_frames(self) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM live_frames").fetchone()[0]

    def db_size_mb(self) -> float:
        try:
            return round(self._db_path.stat().st_size / 1_048_576, 2)
        except OSError:
            return 0.0


# Module-level singleton — imported by server.py
_store: CanStore | None = None


def get_store(retrain_callback: Callable | None = None) -> CanStore:
    global _store
    if _store is None:
        _store = CanStore(retrain_callback=retrain_callback)
    return _store
