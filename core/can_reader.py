from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Optional

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

try:
    import can  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    can = None


@dataclass(frozen=True)
class CANFrame:
    timestamp: float
    arbitration_id: int
    data: bytes
    dlc: int
    channel: str
    stream_id: int


class CANReader(QObject):
    frame_received = pyqtSignal(object)
    mode_changed = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._bus = None
        self._mode = "stopped"
        self._stream_id = 0
        self._simulation_index = 0
        self._sim_state = {
            0x1A2: 500.0,
            0x2B4: 63.0,
            0x3F1: 1850.0,
            0x4C8: 78.0,
            0x5D2: 41.0,
            0x6E7: 558.0,
        }
        self._read_timer = QTimer(self)
        self._read_timer.timeout.connect(self._poll_bus)
        self._sim_timer = QTimer(self)
        self._sim_timer.timeout.connect(self._emit_simulated_frame)

    @property
    def mode(self) -> str:
        return self._mode

    def start(self, stream_id: Optional[int] = None):
        self._stream_id = stream_id if stream_id is not None else self._stream_id + 1
        if self._connect_real_bus():
            self._mode = "live"
            self.mode_changed.emit(self._mode)
            self._read_timer.start(20)
            return
        self._start_simulation()

    def stop(self):
        self._read_timer.stop()
        self._sim_timer.stop()
        if self._bus is not None:
            try:
                self._bus.shutdown()
            except Exception:
                pass
        self._bus = None
        self._mode = "stopped"
        self.mode_changed.emit(self._mode)

    def toggle(self):
        if self._mode == "stopped":
            self.start()
        else:
            self.stop()

    def _connect_real_bus(self) -> bool:
        if can is None:
            return False
        try:
            configs = can.detect_available_configs() or []
        except Exception as exc:  # pragma: no cover - hardware dependent
            self.error_occurred.emit(f"CAN detect failed: {exc}")
            return False

        for config in configs:
            try:
                bustype = config.get("interface") or config.get("bustype")
                channel = config.get("channel")
                if not bustype or channel is None:
                    continue
                self._bus = can.Bus(interface=bustype, channel=channel, receive_own_messages=False)
                return True
            except Exception:
                self._bus = None
                continue
        return False

    def _poll_bus(self):
        if self._bus is None:
            self._start_simulation()
            return
        try:
            msg = self._bus.recv(timeout=0.0)
        except Exception as exc:  # pragma: no cover - hardware dependent
            self.error_occurred.emit(f"CAN read failed, switching to simulation: {exc}")
            self._bus = None
            self._read_timer.stop()
            self._start_simulation()
            return

        if msg is None:
            return
        frame = CANFrame(
            timestamp=getattr(msg, "timestamp", time.time()),
            arbitration_id=int(msg.arbitration_id),
            data=bytes(msg.data),
            dlc=int(msg.dlc),
            channel=str(getattr(msg, "channel", "can0")),
            stream_id=self._stream_id,
        )
        self.frame_received.emit(frame)

    def _start_simulation(self):
        self._read_timer.stop()
        self._mode = "simulation"
        self.mode_changed.emit(self._mode)
        self._schedule_next_sim_frame()

    def _schedule_next_sim_frame(self):
        if self._mode != "simulation":
            return
        self._sim_timer.start(random.randint(50, 100))

    def _emit_simulated_frame(self):
        self._sim_timer.stop()
        ids = [0x1A2, 0x2B4, 0x3F1, 0x4C8, 0x5D2, 0x6E7]
        can_id = ids[self._simulation_index % len(ids)]
        self._simulation_index += 1

        if can_id == 0x1A2:
            value = self._wander(can_id, 386.0, 0.9, 320.0, 418.0)
            raw = int(value / 0.1)
            payload = raw.to_bytes(2, byteorder="big", signed=False) + b"\x00" * 6
        elif can_id == 0x2B4:
            value = self._wander(can_id, 63.0, 1.1, 45.0, 112.0)
            raw = int((value + 40.0) / 0.5)
            payload = raw.to_bytes(2, byteorder="big", signed=False) + b"\x00" * 6
        elif can_id == 0x3F1:
            value = self._wander(can_id, 1850.0, 120.0, 700.0, 5200.0)
            raw = int(value)
            payload = raw.to_bytes(2, byteorder="big", signed=False) + b"\x00" * 6
        elif can_id == 0x4C8:
            value = self._wander(can_id, 78.0, 0.4, 20.0, 100.0)
            raw = int(value / 0.5)
            payload = raw.to_bytes(2, byteorder="big", signed=False) + b"\x00" * 6
        elif can_id == 0x5D2:
            value = self._wander(can_id, 41.0, 2.5, -180.0, 230.0)
            raw = int((value + 400.0) / 0.1)
            payload = raw.to_bytes(2, byteorder="big", signed=False) + b"\x00" * 6
        else:
            value = self._wander(can_id, 58.0, 0.8, 30.0, 110.0)
            raw = int((value + 40.0) / 0.5)
            payload = raw.to_bytes(2, byteorder="big", signed=False) + b"\x00" * 6

        frame = CANFrame(
            timestamp=time.time(),
            arbitration_id=can_id,
            data=payload,
            dlc=len(payload),
            channel="sim-can0",
            stream_id=self._stream_id,
        )
        self.frame_received.emit(frame)
        self._schedule_next_sim_frame()

    def _wander(self, can_id: int, center: float, jitter: float, low: float, high: float) -> float:
        current = self._sim_state.get(can_id, center)
        drift = random.uniform(-jitter, jitter)
        target_pull = (center - current) * 0.08
        updated = max(low, min(high, current + drift + target_pull))
        self._sim_state[can_id] = updated
        return updated
