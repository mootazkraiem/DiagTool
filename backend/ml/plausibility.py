"""Physical plausibility checker.

Decodes raw CAN bytes using signal_map.json and verifies that every
signal value is within its documented physical range.  Returns a
structured result that can be injected directly into an alert context.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_SIGNAL_MAP_PATH = Path(__file__).resolve().parents[1] / "knowledge" / "signal_map.json"
_signal_map: dict[str, Any] | None = None
_signal_map_mtime: float = 0.0


def _load_signal_map() -> dict[str, Any]:
    global _signal_map, _signal_map_mtime
    try:
        mtime = _SIGNAL_MAP_PATH.stat().st_mtime
    except OSError:
        return _signal_map or {}
    if _signal_map is None or mtime != _signal_map_mtime:
        try:
            _signal_map = json.loads(_SIGNAL_MAP_PATH.read_text(encoding="utf-8"))
            _signal_map_mtime = mtime
        except Exception:
            _signal_map = {}
    return _signal_map


def _find_entry(can_id_hex: str) -> dict[str, Any] | None:
    smap = _load_signal_map()
    key = can_id_hex.upper().lstrip("0X") if can_id_hex else ""
    for k, v in smap.items():
        if k.upper().lstrip("0X") == key:
            return v
    return None


def _decode_signal(raw: bytes, sig: dict[str, Any]) -> float | None:
    """Decode one signal from raw CAN payload using DBC scale/offset."""
    scale = sig.get("scale", 1.0)
    offset = sig.get("offset", 0.0)
    start_bit = sig.get("start_bit")
    length = sig.get("length")

    # Prefer start_bit/length (from DBC parser) over bytes list
    if start_bit is not None and length is not None:
        byte_idx = start_bit // 8
        if byte_idx >= len(raw):
            return None
        bit_offset = start_bit % 8
        # Bytes needed for any signal width (8-, 16-, 32-, 64-bit)
        n_bytes = max(1, (bit_offset + length + 7) // 8)
        n_bytes = min(n_bytes, len(raw) - byte_idx)
        if n_bytes <= 0:
            return None
        chunk = raw[byte_idx: byte_idx + n_bytes]
        if len(chunk) < n_bytes:
            chunk = chunk + b"\x00" * (n_bytes - len(chunk))
        raw_val = int.from_bytes(chunk, "little")
        raw_val = (raw_val >> bit_offset) & ((1 << length) - 1)
    else:
        # Fallback: use bytes list
        byte_indices = sig.get("bytes", [])
        if not byte_indices or byte_indices[0] >= len(raw):
            return None
        if len(byte_indices) >= 2:
            b0 = raw[byte_indices[0]] if byte_indices[0] < len(raw) else 0
            b1 = raw[byte_indices[1]] if byte_indices[1] < len(raw) else 0
            raw_val = (b0 << 8) | b1
        else:
            raw_val = raw[byte_indices[0]]

    return raw_val * scale + offset


def check(can_id_hex: str, raw_bytes: list[int]) -> dict[str, Any]:
    """
    Check physical plausibility of a CAN frame.

    Returns:
        {
            'checked': bool,        # False if CAN ID not in signal_map
            'passed': bool,         # True if all signals within range
            'violations': [...],    # list of {signal, value, min, max, unit}
            'decoded_signals': [...] # all decoded values (for context)
        }
    """
    entry = _find_entry(can_id_hex)
    if entry is None:
        return {"checked": False, "passed": True, "violations": [], "decoded_signals": []}

    signals = entry.get("signals", [])
    if not signals:
        return {"checked": True, "passed": True, "violations": [], "decoded_signals": []}

    raw = bytes(raw_bytes[:8])
    violations: list[dict] = []
    decoded: list[dict] = []

    for sig in signals:
        name = sig.get("name", "?")
        unit = sig.get("unit", "")
        lo = sig.get("min_normal")
        hi = sig.get("max_normal")

        value = _decode_signal(raw, sig)
        if value is None:
            continue

        decoded.append({"signal": name, "value": round(value, 3), "unit": unit})

        if lo is not None and hi is not None:
            if value < lo or value > hi:
                violations.append({
                    "signal": name,
                    "value": round(value, 3),
                    "min_normal": lo,
                    "max_normal": hi,
                    "unit": unit,
                    "excess": round(max(lo - value, value - hi, 0), 3),
                })

    return {
        "checked": True,
        "passed": len(violations) == 0,
        "violations": violations,
        "decoded_signals": decoded,
    }
