"""CAN signal decoder — maps raw CAN-ID + byte payload to human-readable signal values.

Signal definitions live in backend/knowledge/signal_map.json.
The encoding contract (scale/offset/byte-layout) matches what server.py writes
into the live buffer, so decoded values round-trip to the original signals.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_MAP_PATH = Path(__file__).resolve().parents[1] / "knowledge" / "signal_map.json"
_signal_map: dict[str, Any] | None = None


def _load() -> dict[str, Any]:
    global _signal_map
    if _signal_map is None:
        _signal_map = json.loads(_MAP_PATH.read_text(encoding="utf-8"))
    return _signal_map


def _normalise_id(can_id: str | int) -> str:
    """Return uppercase 0x-prefixed hex string e.g. '0x1A2'."""
    if isinstance(can_id, int):
        return f"0x{can_id:03X}"
    s = str(can_id).strip().upper()
    if s.startswith("0X"):
        return "0x" + s[2:]
    return s


def decode(can_id: str | int, bytes_: list[int]) -> list[dict[str, Any]]:
    """Decode a single CAN frame into a list of named signal readings.

    Each entry: {signal, value, unit, out_of_range, delta, nominal, system}
    Returns an empty list for unknown CAN-IDs.
    """
    key = _normalise_id(can_id)
    smap = _load()
    entry = smap.get(key)
    if entry is None:
        return []

    system_name = entry["system"]
    results: list[dict[str, Any]] = []

    for sig in entry["signals"]:
        decode_type: str = sig.get("decode", "uint8")
        byte_indices: list[int] = sig["bytes"]
        scale: float = float(sig["scale"])
        offset: float = float(sig["offset"])
        min_n: float = float(sig["min_normal"])
        max_n: float = float(sig["max_normal"])
        nominal: float = float(sig["nominal"])

        # Guard: make sure we have enough bytes
        if not byte_indices or max(byte_indices) >= len(bytes_):
            continue

        if decode_type == "uint16_be":
            raw = (bytes_[byte_indices[0]] << 8) | bytes_[byte_indices[1]]
        else:
            raw = bytes_[byte_indices[0]]

        value = round(raw * scale + offset, 3)
        out_of_range = value < min_n or value > max_n
        delta = round(value - nominal, 3)

        results.append({
            "signal":       sig["name"],
            "system":       system_name,
            "value":        value,
            "unit":         sig["unit"],
            "out_of_range": out_of_range,
            "delta":        delta,
            "nominal":      nominal,
            "min_normal":   min_n,
            "max_normal":   max_n,
        })

    return results


def describe(can_id: str | int) -> str | None:
    """Return the system name for a CAN-ID, or None if unknown."""
    smap = _load()
    entry = smap.get(_normalise_id(can_id))
    return entry["system"] if entry else None
