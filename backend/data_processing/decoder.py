from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

from backend.data_processing.can_reader import CANFrame


@dataclass(frozen=True)
class DecodedSignal:
    stream_id: int
    timestamp: float
    can_id: int
    signal_name: str
    value: float
    unit: str
    severity: str
    frame_key: str


class VehicleDecoder(QObject):
    signal_decoded = pyqtSignal(object)
    profile_changed = pyqtSignal(str)
    profile_loaded = pyqtSignal(str, int)
    error_occurred = pyqtSignal(str)

    def __init__(self, profile_path: Optional[str] = None, parent: Optional[QObject] = None):
        super().__init__(parent)
        default_path = Path(__file__).resolve().parents[2] / "data" / "uds" / "default_vehicle.json"
        self._profile_path = Path(profile_path) if profile_path else default_path
        self._definitions = {}
        self.load_profile(str(self._profile_path))

    @property
    def profile_path(self) -> str:
        return str(self._profile_path)

    def load_profile(self, profile_path: str):
        path = Path(profile_path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            self.error_occurred.emit(f"Failed to load decoder profile '{path.name}': {exc}")
            return

        self._profile_path = path
        self._definitions = {}
        for can_id_text, definition in payload.items():
            can_id = int(can_id_text, 16)
            self._definitions[can_id] = definition
        self.profile_changed.emit(str(path))
        self.profile_loaded.emit(path.name, len(self._definitions))

    def decode_frame(self, frame: CANFrame) -> Optional[DecodedSignal]:
        definition = self._definitions.get(frame.arbitration_id)
        if definition is None:
            return None

        try:
            raw_value = self._extract_raw_value(frame.data, definition)
        except Exception as exc:
            self.error_occurred.emit(f"Decode failed for 0x{frame.arbitration_id:X}: {exc}")
            return None
        scale = float(definition.get("scale", 1.0))
        offset = float(definition.get("offset", 0.0))
        value = raw_value * scale + offset
        severity = self._severity_for(value, definition)

        signal = DecodedSignal(
            stream_id=frame.stream_id,
            timestamp=frame.timestamp,
            can_id=frame.arbitration_id,
            signal_name=str(definition.get("signal_name", f"0x{frame.arbitration_id:X}")),
            value=round(value, 3),
            unit=str(definition.get("unit", "")),
            severity=severity,
            frame_key=f"{frame.stream_id}:{frame.arbitration_id}:{frame.timestamp:.9f}",
        )
        self.signal_decoded.emit(signal)
        return signal

    def _extract_raw_value(self, data: bytes, definition: dict) -> int:
        signed = bool(definition.get("signed", False))
        byte_order = str(definition.get("byte_order", definition.get("endianness", "big"))).lower()

        if "start_bit" in definition or "bit_length" in definition:
            default_start_bit = int(definition.get("start_byte", 0)) * 8
            start_bit = int(definition.get("start_bit", default_start_bit))
            bit_length = int(definition.get("bit_length", definition.get("length", 1) * 8))
            payload = int.from_bytes(data, byteorder="big", signed=False)
            total_bits = len(data) * 8
            if bit_length <= 0 or start_bit < 0 or start_bit + bit_length > total_bits:
                raise ValueError("Invalid bit extraction range")
            if byte_order == "little":
                payload = int.from_bytes(data, byteorder="little", signed=False)
                shift = start_bit
            else:
                shift = total_bits - start_bit - bit_length
            raw_value = (payload >> shift) & ((1 << bit_length) - 1)
            if signed and raw_value & (1 << (bit_length - 1)):
                raw_value -= 1 << bit_length
            return raw_value

        start_byte = int(definition.get("start_byte", 0))
        length = int(definition.get("length", 1))
        raw_slice = data[start_byte : start_byte + length]
        if not raw_slice:
            raise ValueError("Empty payload slice")
        endian = "little" if byte_order == "little" else "big"
        return int.from_bytes(raw_slice, byteorder=endian, signed=signed)

    def _severity_for(self, value: float, definition: dict) -> str:
        safe_min = definition.get("safe_min")
        safe_max = definition.get("safe_max")
        if safe_min is None or safe_max is None:
            return "normal"

        safe_min = float(safe_min)
        safe_max = float(safe_max)
        span = max(safe_max - safe_min, 1.0)
        warn_band = span * 0.08
        if value < safe_min or value > safe_max:
            return "critical"
        if value <= safe_min + warn_band or value >= safe_max - warn_band:
            return "warning"
        return "normal"
