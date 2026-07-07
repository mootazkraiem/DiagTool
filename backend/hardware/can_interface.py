"""Live CAN hardware reader.

Connects to a real CAN adapter (ELM327 via slcan, PEAK PCAN via pcan,
KVASER via kvaser, SocketCAN on Linux) using python-can, then feeds frames
into the same live_signals_buffer / live_alerts_buffer already used by the
simulator, so all downstream endpoints (/api/live/signals, /api/live/alerts)
work unchanged.

Usage (from server.py):
    from backend.hardware.can_interface import CanHardwareReader
    hw_reader = CanHardwareReader(runtime_engine, runtime_stats,
                                  live_signals_buffer, live_alerts_buffer,
                                  runtime_lock)
    hw_reader.connect("pcan", channel="PCAN_USBBUS1", bitrate=500000)
    hw_reader.disconnect()
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Supported interface types → python-can bustype strings
_INTERFACE_MAP: dict[str, str] = {
    "pcan":     "pcan",       # PEAK PCAN USB
    "kvaser":   "kvaser",     # Kvaser USB
    "socketcan": "socketcan", # SocketCAN (Linux)
    "slcan":    "slcan",      # ELM327 / serial CAN adapters
    "vector":   "vector",     # Vector CANalyzer hardware
    "ixxat":    "ixxat",      # IXXAT USB-to-CAN
    "usb2can":  "usb2can",    # 8devices USB2CAN
    "virtual":  "virtual",    # python-can virtual bus (testing)
}

_BUFFER_MAX = 2000


_FUSION_LAYER_KEYS = {"timing", "payload", "ml", "persistence"}


def _dominant_layer(reason: str) -> str:
    # Only compare the four inputs that actually feed ScoringEngine.score()/fusion_score
    # (backend/ml/runtime/scoring_engine.py). The reason string also carries diagnostic-only
    # fields "freq" (raw Hz) and "can_id_entropy" (raw bits) that were never part of fusion
    # scoring but, being numerically much larger than the 0-2 range of the real layer scores,
    # always won the old unfiltered max(). Same defect and fix as backend/api/server.py's
    # _dominant_layer/_reason_bucket.
    vals: dict[str, float] = {}
    for part in str(reason).split(","):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        k = k.strip().lower()
        if k not in _FUSION_LAYER_KEYS:
            continue
        try:
            vals[k] = float(v.strip())
        except ValueError:
            continue
    if not vals:
        return "unknown"
    dom = max(vals, key=lambda x: vals[x])
    return {"timing": "timing", "payload": "payload", "ml": "ml", "persistence": "temporal"}.get(dom, dom)


class CanHardwareReader:
    """Reads frames from real CAN hardware and scores them through RealtimeEngine."""

    def __init__(
        self,
        runtime_engine: Any,
        runtime_stats: Any,
        signals_buffer: list[dict[str, Any]],
        alerts_buffer: list[dict[str, Any]],
        lock: threading.Lock,
        vehicle_id: str = "",
    ) -> None:
        self._engine = runtime_engine
        self._stats = runtime_stats
        self._signals = signals_buffer
        self._alerts = alerts_buffer
        self._lock = lock
        self._vehicle_id = vehicle_id

        self._bus: Any = None          # python-can Bus
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self.is_connected = False
        self.interface_type = ""
        self.channel = ""
        self.bitrate = 500_000
        self.frames_received = 0
        self.alert_count = 0
        self.current_score = 0.0
        self.error: str = ""
        self.connected_at: Optional[float] = None

    # ── Public API ─────────────────────────────────────────────────────────────

    def connect(
        self,
        interface: str,
        channel: str = "",
        bitrate: int = 500_000,
        vehicle_id: str = "",
    ) -> None:
        """Open the CAN bus and start the reader thread.

        Args:
            interface: One of 'pcan', 'kvaser', 'socketcan', 'slcan', 'virtual', etc.
            channel:   Adapter channel, e.g. 'PCAN_USBBUS1', 'can0', '/dev/ttyUSB0'.
                       If empty, python-can uses the default for that interface.
            bitrate:   CAN bus speed in bps (default 500 000).
            vehicle_id: Optional vehicle profile for DBC decode in future use.
        """
        if self.is_connected:
            raise RuntimeError("Already connected — call disconnect() first")

        import can

        bustype = _INTERFACE_MAP.get(interface.lower())
        if bustype is None:
            raise ValueError(
                f"Unknown interface '{interface}'. Supported: {list(_INTERFACE_MAP)}"
            )

        self.interface_type = interface.lower()
        self.channel = channel
        self.bitrate = bitrate
        if vehicle_id:
            self._vehicle_id = vehicle_id
        # Score against the matching trained model bundle for this vehicle instead
        # of always falling back to "general" (same fix as the replay paths).
        self._engine.vehicle_id = self._vehicle_id or "general"
        self.error = ""

        bus_kwargs: dict[str, Any] = {"interface": bustype, "bitrate": bitrate}
        if channel:
            bus_kwargs["channel"] = channel

        if self._bus is not None:
            # Defensive: a prior session may have left a stale handle open
            # (e.g. after a recv() error) without going through disconnect().
            try:
                self._bus.shutdown()
            except Exception:
                pass
            self._bus = None

        try:
            self._bus = can.interface.Bus(**bus_kwargs)
        except Exception as exc:
            self.error = str(exc)
            raise RuntimeError(f"Failed to open CAN bus ({interface}, {channel}): {exc}") from exc

        self._stop_event.clear()
        self.frames_received = 0
        self.alert_count = 0
        self.current_score = 0.0
        self.connected_at = time.time()
        self.is_connected = True

        self._thread = threading.Thread(
            target=self._read_loop, daemon=True, name="can-hw-reader"
        )
        self._thread.start()
        logger.info(
            "[HW] Connected  interface=%s  channel=%s  bitrate=%d",
            interface, channel or "(default)", bitrate
        )

    def disconnect(self) -> None:
        """Stop the reader thread and close the CAN bus."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None

        if self._bus is not None:
            try:
                self._bus.shutdown()
            except Exception:
                pass
            self._bus = None

        self.is_connected = False
        # Reset the shared engine back to "general" so the synthetic /vehicle
        # endpoint (resumed after disconnect) doesn't keep scoring generic demo
        # data against this hardware session's vehicle-specific model.
        self._engine.vehicle_id = "general"
        logger.info(
            "[HW] Disconnected  frames=%d  alerts=%d",
            self.frames_received, self.alert_count
        )

    def status(self) -> dict[str, Any]:
        return {
            "is_connected":   self.is_connected,
            "interface_type": self.interface_type,
            "channel":        self.channel,
            "bitrate":        self.bitrate,
            "vehicle_id":     self._vehicle_id,
            "frames_received": self.frames_received,
            "alert_count":    self.alert_count,
            "current_score":  round(self.current_score, 4),
            "error":          self.error,
            "connected_at":   self.connected_at,
            "uptime_seconds": round(time.time() - self.connected_at, 1)
                              if self.connected_at else 0.0,
        }

    # ── Internal read loop ─────────────────────────────────────────────────────

    def _read_loop(self) -> None:
        from backend.ml.runtime.realtime_engine import CanFrame
        from backend.decoding.dbc_manager import get_manager

        mgr = get_manager()

        while not self._stop_event.is_set():
            try:
                msg = self._bus.recv(timeout=0.5)
            except Exception as exc:
                logger.error("[HW] recv error: %s", exc)
                self.error = str(exc)
                self.is_connected = False
                if self._bus is not None:
                    try:
                        self._bus.shutdown()
                    except Exception:
                        pass
                    self._bus = None
                break

            if msg is None:
                continue

            ts = msg.timestamp
            can_id = msg.arbitration_id
            # Pad to 8 bytes
            raw = list(msg.data) + [0] * (8 - len(msg.data))
            payload = tuple(raw[:8])

            try:
                self._score_and_buffer(ts, can_id, payload, mgr)
            except Exception as exc:
                logger.warning("[HW] score error: %s", exc)

    def _score_and_buffer(
        self,
        ts: float,
        can_id: int,
        payload: tuple,
        mgr: Any,
    ) -> None:
        from backend.ml.runtime.realtime_engine import CanFrame

        with self._lock:
            out = self._engine.process_frame(
                CanFrame(timestamp=ts, can_id=can_id, payload=payload)
            )

        self._stats.on_frame()
        score = float(out["score"]["fusion_score"])
        self._stats.on_score(score)
        self.current_score = score
        self.frames_received += 1

        # DBC decode if vehicle is known
        signals_list: list[dict] = []
        if self._vehicle_id:
            decoded = mgr.decode(self._vehicle_id, can_id, list(payload))
            signals_list = [
                {
                    "name":         s.name,
                    "value":        s.value,
                    "unit":         s.unit,
                    "out_of_range": s.out_of_range,
                    "system":       s.system,
                }
                for s in decoded
            ]

        signal_item: dict[str, Any] = {
            "timestamp":    ts,
            "can_id":       f"0x{can_id:03X}",
            "b0": payload[0], "b1": payload[1],
            "b2": payload[2], "b3": payload[3],
            "b4": payload[4], "b5": payload[5],
            "b6": payload[6], "b7": payload[7],
            "anomaly_score": score,
            "severity":     str(out["score"]["risk_level"]),
            "signals":      signals_list,
        }

        with self._lock:
            self._signals.append(signal_item)
            if len(self._signals) > _BUFFER_MAX:
                del self._signals[:-_BUFFER_MAX]

            if out["alert"] is not None:
                self._stats.on_alert(out["alert"])
                alert = out["alert"]
                self._alerts.append({
                    "timestamp":                float(alert.get("timestamp", ts)),
                    "severity":                 str(alert.get("risk_level", "UNKNOWN")),
                    "attack_type":              "hardware_live",
                    "can_id":                   f"0x{int(alert.get('can_id', can_id)):03X}",
                    "score":                    float(alert.get("score", score)),
                    "dominant_detection_layer": _dominant_layer(str(alert.get("reason", ""))),
                    "reason":                   str(alert.get("reason", "")),
                    "replay_source":            "hardware",
                    "b0": payload[0], "b1": payload[1],
                    "b2": payload[2], "b3": payload[3],
                    "b4": payload[4], "b5": payload[5],
                    "b6": payload[6], "b7": payload[7],
                })
                if len(self._alerts) > _BUFFER_MAX:
                    del self._alerts[:-_BUFFER_MAX]
                self.alert_count = len(self._alerts)
