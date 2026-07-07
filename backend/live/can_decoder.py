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


def _extract_bits(bytes_: list[int], start_bit: int, length: int, big_endian: bool) -> int | None:
    """Extract `length` bits starting at `start_bit` from a byte payload.

    big_endian=True: start_bit counts from the MSB of the whole payload (Motorola-style).
    big_endian=False: start_bit counts from the LSB of the whole payload (Intel-style).
    Returns None if the requested bit range doesn't fit in the payload.
    """
    total_bits = len(bytes_) * 8
    if length <= 0 or start_bit < 0 or start_bit + length > total_bits:
        return None

    raw = 0
    for i in range(length):
        bit_pos = start_bit + i
        byte_idx = bit_pos // 8
        if big_endian:
            bit_in_byte = 7 - (bit_pos % 8)
            raw = (raw << 1) | ((bytes_[byte_idx] >> bit_in_byte) & 1)
        else:
            bit_in_byte = bit_pos % 8
            raw |= ((bytes_[byte_idx] >> bit_in_byte) & 1) << i
    return raw


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
        decode_type: str = sig.get("decode", "uint8_be")
        start_bit: int = int(sig.get("start_bit", 0))
        length: int = int(sig.get("length", 8))
        scale: float = float(sig["scale"])
        offset: float = float(sig["offset"])
        min_n: float = float(sig["min_normal"])
        max_n: float = float(sig["max_normal"])
        nominal: float = float(sig["nominal"])

        big_endian = decode_type.endswith("_be")
        signed = decode_type.startswith("int")

        raw = _extract_bits(bytes_, start_bit, length, big_endian)
        if raw is None:
            continue

        if signed and raw & (1 << (length - 1)):
            raw -= 1 << length

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
