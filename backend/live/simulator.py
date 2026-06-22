"""Continuous live CAN simulator.

Runs as a background daemon thread at ~10 fps, rotating through the same
4 CAN domains as the /vehicle endpoint so the ML engine builds realistic
per-ID timing and payload statistics.

Every ~60 s a DoS burst injects frames at ~200 fps for 4 s, reliably
triggering the timing-layer anomaly detector and producing CRITICAL alerts
in live_alerts_buffer that the C# app can pick up via /api/live/alerts.

Raw byte values are stored alongside each alert entry so that
/api/explain/{index} can decode signal values without a second lookup.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

from backend.api.mock_signals import MockSignals
from backend.ml.runtime.realtime_engine import CanFrame

logger = logging.getLogger("can_ai_backend.simulator")

_NORMAL_INTERVAL = 0.10     # 10 fps
_DOS_INTERVAL    = 0.005    # 200 fps during burst
_DOS_EVERY_SEC   = 60       # burst period
_DOS_DURATION_SEC = 4       # burst length
_DOS_FIRST_DELAY  = 30      # seconds before first burst


def _dominant_layer(reason: str) -> str:
    vals: dict[str, float] = {}
    for part in str(reason).split(","):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        try:
            vals[k.strip().lower()] = float(v.strip())
        except ValueError:
            continue
    if not vals:
        return "unknown"
    dom = max(vals, key=vals.get)  # type: ignore[arg-type]
    return {"timing": "timing", "payload": "payload", "ml": "ml", "persistence": "temporal"}.get(dom, dom)


class LiveSimulator:
    """Continuous CAN frame generator and ML scorer."""

    def __init__(
        self,
        runtime_engine: Any,
        runtime_stats: Any,
        signals_buffer: list[dict[str, Any]],
        alerts_buffer: list[dict[str, Any]],
        lock: threading.Lock,
    ) -> None:
        self._engine = runtime_engine
        self._stats = runtime_stats
        self._signals = signals_buffer
        self._alerts = alerts_buffer
        self._lock = lock
        self._generator = MockSignals()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._tick = 0
        self._session_start: float | None = None

        self.is_running = False
        self.current_score = 0.0
        self.alert_count = 0
        self.dos_active = False
        self.frames_generated = 0

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            logger.info("[SIM] Already running — ignoring start()")
            return
        self._stop_event.clear()
        self._session_start = time.time()
        self.frames_generated = 0
        self.alert_count = 0
        self.current_score = 0.0
        self.dos_active = False
        self._thread = threading.Thread(target=self._run, daemon=True, name="live-simulator")
        self._thread.start()
        self.is_running = True
        logger.info("[SIM] Simulator started")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
        self.is_running = False
        self.dos_active = False
        logger.info("[SIM] Simulator stopped  frames=%d alerts=%d", self.frames_generated, self.alert_count)

    def session_duration(self) -> float:
        return time.time() - self._session_start if self._session_start else 0.0

    # ── Internal loop ─────────────────────────────────────────────────────────

    def _run(self) -> None:
        last_dos_at = time.time() + _DOS_FIRST_DELAY - _DOS_EVERY_SEC
        dos_end = 0.0

        while not self._stop_event.is_set():
            now = time.time()

            # DoS burst scheduling
            if not self.dos_active and (now - last_dos_at) >= _DOS_EVERY_SEC:
                self.dos_active = True
                dos_end = now + _DOS_DURATION_SEC
                last_dos_at = now
                logger.info("[SIM] DoS burst started")

            if self.dos_active and now >= dos_end:
                self.dos_active = False
                logger.info("[SIM] DoS burst ended  alerts=%d  score=%.3f", self.alert_count, self.current_score)

            try:
                ts, can_id, payload = self._next_frame()
                self._score_and_buffer(ts, can_id, payload)
            except Exception as exc:
                logger.warning("[SIM] Frame error: %s", exc)

            sleep = _DOS_INTERVAL if self.dos_active else _NORMAL_INTERVAL
            self._stop_event.wait(timeout=sleep)

    def _next_frame(self) -> tuple[float, int, tuple[int, ...]]:
        self._tick = (self._tick + 1) % 4
        snap = self._generator.generate()
        ts = time.time()

        if self._tick == 0:
            can_id = 0x1A2
            v = int(snap.get("BatteryVoltage", 395.0) * 10)
            b0, b1 = (v >> 8) & 0xFF, v & 0xFF
            b2 = int(snap.get("SOC", 78.0) * 2) & 0xFF
            b3 = int((snap.get("BatteryTemp", 31.0) + 40.0) * 2) & 0xFF
            payload = (b0, b1, b2, b3, 0, 0, 0, 0)
        elif self._tick == 1:
            can_id = 0x3F1
            rpm = int(snap.get("MotorRPM", 3100))
            b0, b1 = (rpm >> 8) & 0xFF, rpm & 0xFF
            b2 = int((snap.get("MotorTemp", 48.0) + 40.0)) & 0xFF
            b3 = int(snap.get("MotorTorque", 120.0) * 2) & 0xFF
            payload = (b0, b1, b2, b3, 0, 0, 0, 0)
        elif self._tick == 2:
            can_id = 0x5D2
            spd = int(snap.get("VehicleSpeed", 60.0) * 100)
            b0, b1 = (spd >> 8) & 0xFF, spd & 0xFF
            b2 = int(snap.get("BrakePedal", 0.0) * 10) & 0xFF
            b3 = int(snap.get("AcceleratorPedal", 18.0) * 2) & 0xFF
            payload = (b0, b1, b2, b3, 0, 0, 0, 0)
        else:
            can_id = 0x6E7
            b0 = int((snap.get("InverterTemp", 42.0) + 40.0)) & 0xFF
            b1 = int(snap.get("CoolingPumpSpeed", 20)) & 0xFF
            b2 = int(snap.get("CellVoltageDiff", 0.05) * 1000) & 0xFF
            b3 = int(snap.get("BatteryCoolingState", 0)) & 0xFF
            payload = (b0, b1, b2, b3, 0, 0, 0, 0)

        return ts, can_id, payload

    def _score_and_buffer(self, ts: float, can_id: int, payload: tuple[int, ...]) -> None:
        with self._lock:
            out = self._engine.process_frame(CanFrame(timestamp=ts, can_id=can_id, payload=payload))

        self._stats.on_frame()
        score = float(out["score"]["fusion_score"])
        self._stats.on_score(score)
        self.current_score = score
        self.frames_generated += 1

        signal_item: dict[str, Any] = {
            "timestamp":    ts,
            "can_id":       f"0x{can_id:03X}",
            "b0": payload[0], "b1": payload[1],
            "b2": payload[2], "b3": payload[3],
            "b4": payload[4], "b5": payload[5],
            "b6": payload[6], "b7": payload[7],
            "anomaly_score": score,
            "severity":     str(out["score"]["risk_level"]),
        }

        with self._lock:
            self._signals.append(signal_item)
            if len(self._signals) > 2000:
                del self._signals[:-2000]

            if out["alert"] is not None:
                self._stats.on_alert(out["alert"])
                alert = out["alert"]
                self._alerts.append({
                    "timestamp":               float(alert.get("timestamp", ts)),
                    "severity":                str(alert.get("risk_level", "UNKNOWN")),
                    "attack_type":             "dos_burst" if self.dos_active else "runtime",
                    "can_id":                  f"0x{int(alert.get('can_id', can_id)):03X}",
                    "score":                   float(alert.get("score", score)),
                    "dominant_detection_layer": _dominant_layer(str(alert.get("reason", ""))),
                    "reason":                  str(alert.get("reason", "")),
                    "replay_source":           "live_sim",
                    # raw bytes — stored so /api/explain/{i} can decode signal values
                    "b0": payload[0], "b1": payload[1],
                    "b2": payload[2], "b3": payload[3],
                    "b4": payload[4], "b5": payload[5],
                    "b6": payload[6], "b7": payload[7],
                })
                if len(self._alerts) > 2000:
                    del self._alerts[:-2000]
                self.alert_count = len(self._alerts)
