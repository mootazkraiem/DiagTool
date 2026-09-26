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
                                  runtime_lock, engine_factory=model_status.live_engine)
    hw_reader.connect("pcan", channel="PCAN_USBBUS1", bitrate=500000, vehicle_id="kia_ev6")

Each connection scores through its own RealtimeEngine, built by ``engine_factory``
for exactly the selected vehicle (backend.ml.runtime.model_status.live_engine):
a promoted clean-2 family loads through load_id_family, a legacy vehicle gets
its legacy bundle, and a held-back, unavailable or unknown selection refuses the
connection with the reason. The server's shared engine is never re-pointed.
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

# A healthy CAN bus produces frames far more often than this — if none arrive
# for this long while the link is otherwise "up", treat it as disconnected.
# A silently unplugged adapter never raises an exception (recv() just times
# out and returns None forever), so exception-based detection alone misses it.
_STALE_AFTER_SECONDS = 5.0


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
        engine_factory: Any = None,
    ) -> None:
        # The engine a connection scores with; built per connection by
        # engine_factory(vehicle_id). Without a factory (tests, tools) the engine
        # passed in is used as it is and its model is never changed here.
        self._engine = runtime_engine
        self._engine_factory = engine_factory
        self._stats = runtime_stats
        self._signals = signals_buffer
        self._alerts = alerts_buffer
        self._lock = lock
        self._vehicle_id = vehicle_id

        self._bus: Any = None          # python-can Bus
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self._link_up = False          # raw "did the read loop crash" flag
        self.last_frame_at: Optional[float] = None  # last time a real frame arrived
        self.interface_type = ""
        self.channel = ""
        self.bitrate = 500_000
        self.frames_received = 0
        self.alert_count = 0
        self.current_score = 0.0
        self.error: str = ""
        self.connected_at: Optional[float] = None

    @property
    def is_connected(self) -> bool:
        """True only while the link is up AND frames are still actually arriving.

        A dead/unplugged adapter that never raises (recv() just times out
        forever) would otherwise report "connected" indefinitely — this is
        what let stale/simulator data keep displaying for hours after the
        real hardware was physically disconnected.
        """
        if not self._link_up:
            return False
        reference = self.last_frame_at if self.last_frame_at is not None else self.connected_at
        if reference is None:
            return False
        return (time.time() - reference) < _STALE_AFTER_SECONDS

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
        if self._link_up:
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
        # Resolve the model before touching the bus: a selection that cannot be
        # used live (held back, no clean model, unknown, or a clean family that
        # fails validation) refuses the connection with its reason. Assigning
        # vehicle_id to an existing engine did not load the clean-2 family, which
        # is resolved when an engine is built.
        if self._engine_factory is not None:
            self._engine = self._engine_factory(vehicle_id or "general")
        self._vehicle_id = vehicle_id
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
        self.last_frame_at = None
        self._link_up = True

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

        self._link_up = False
        self.last_frame_at = None
        # Clear the shared buffers so stale hardware frames can never be
        # served again after this point — previously these buffers were left
        # untouched on disconnect, so /api/live/signals and /api/live/alerts
        # kept returning hours-old data with nothing to say it was stale.
        with self._lock:
            self._signals.clear()
            self._alerts.clear()
        # The session engine (and its model) is dropped; the next connection
        # builds its own for whatever vehicle it selects.
        if self._engine_factory is not None:
            self._engine = None
        logger.info(
            "[HW] Disconnected  frames=%d  alerts=%d",
            self.frames_received, self.alert_count
        )

    def status(self) -> dict[str, Any]:
        seconds_since_last_frame = (
            round(time.time() - self.last_frame_at, 1)
            if self.last_frame_at is not None else None
        )
        return {
            "is_connected":   self.is_connected,
            "link_up":        self._link_up,  # raw link state, before the staleness check
            "stale":          self._link_up and not self.is_connected,
            "seconds_since_last_frame": seconds_since_last_frame,
            "interface_type": self.interface_type,
            "channel":        self.channel,
            "bitrate":        self.bitrate,
            "vehicle_id":     self._vehicle_id,
            "model_status":   (getattr(self._engine, "model_status", None).to_dict()
                               if getattr(self._engine, "model_status", None) is not None else None),
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
            except ValueError as exc:
                # A single malformed line from the adapter (e.g. transient
                # serial noise glued two frames together) — this is not a
                # dead connection, just one bad frame. Skip it and keep
                # reading instead of tearing down the whole session over it.
                logger.warning("[HW] Skipped malformed frame: %s", exc)
                continue
            except Exception as exc:
                logger.error("[HW] recv error: %s", exc)
                self.error = str(exc)
                self._link_up = False
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

        self.last_frame_at = time.time()  # wall-clock arrival time, for staleness checks
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
