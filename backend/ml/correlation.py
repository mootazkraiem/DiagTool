"""Cross-signal correlation checker.

Detects physically impossible combinations of signals across CAN IDs —
e.g. high RPM while throttle is at zero, or brake and throttle both fully
pressed at the same time.

Each rule aligns frames from two CAN IDs by nearest timestamp
(pd.merge_asof, tolerance 100 ms) and applies a simple predicate.
Violations are written back to the original DataFrame as boolean flags.

Adds columns
------------
    correlation_violation  bool   — True if any rule fires on this frame
    correlation_detail     str    — human-readable contradiction description
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


_SIGNAL_MAP_PATH = Path(__file__).resolve().parents[1] / "knowledge" / "signal_map.json"
_signal_map: dict[str, Any] | None = None


def _load_signal_map() -> dict[str, Any]:
    global _signal_map
    if _signal_map is None:
        try:
            _signal_map = json.loads(_SIGNAL_MAP_PATH.read_text(encoding="utf-8"))
        except Exception:
            _signal_map = {}
    return _signal_map


def _decode_uint_le(raw: bytes, start_bit: int, length: int, scale: float, offset: float) -> float | None:
    try:
        val = int.from_bytes(raw[:8], "little")
        mask = (1 << length) - 1
        return ((val >> start_bit) & mask) * scale + offset
    except Exception:
        return None


def _signal_value(raw_bytes: list[int], can_id_hex: str, sig_name: str) -> float | None:
    smap = _load_signal_map()
    norm = can_id_hex.upper().lstrip("0X")
    entry = next((v for k, v in smap.items() if k.upper().lstrip("0X") == norm), None)
    if entry is None:
        return None
    sig = next((s for s in entry.get("signals", []) if s["name"] == sig_name), None)
    if sig is None:
        return None
    return _decode_uint_le(bytes(raw_bytes[:8]),
                           sig.get("start_bit", 0), sig.get("length", 8),
                           sig.get("scale", 1.0), sig.get("offset", 0.0))


# ── Rule definitions ──────────────────────────────────────────────────────────
# Each rule: can_id_a/sig_a decoded against can_id_b/sig_b.
# predicate(val_a, val_b) -> (violated: bool, detail: str)

_RULES: list[dict] = [
    {
        "name":     "rpm_throttle_contradiction",
        "can_id_a": "0x316", "sig_a": "N",    # EMS11 — engine RPM
        "can_id_b": "0x329", "sig_b": "TPS",  # EMS12 — throttle position
        "predicate": lambda rpm, tps: (
            rpm > 3_000 and tps < 5.0,
            f"RPM {rpm:.0f} but throttle {tps:.1f}% — engine racing with no input",
        ),
    },
    {
        "name":     "high_speed_engine_off",
        "can_id_a": "0x316", "sig_a": "N",    # EMS11 — engine RPM (start_bit=16, length=16, scale=0.25)
        "can_id_b": "0x316", "sig_b": "VS",   # EMS11 — vehicle speed (start_bit=48, length=8, scale=1.0)
        "predicate": lambda rpm, spd: (
            spd > 30.0 and rpm < 400.0,
            f"Speed {spd:.0f} km/h but RPM {rpm:.0f} — vehicle moving with engine off",
        ),
    },
    {
        "name":     "throttle_engine_off",
        "can_id_a": "0x329", "sig_a": "TPS",  # EMS12 — throttle position %
        "can_id_b": "0x316", "sig_b": "N",    # EMS11 — engine RPM
        "predicate": lambda tps, rpm: (
            tps > 25.0 and rpm < 100.0,
            f"Throttle {tps:.1f}% but RPM {rpm:.0f} — throttle signal injected while engine off",
        ),
    },
    {
        "name":     "overtemp_engine_off",
        "can_id_a": "0x329", "sig_a": "TEMP_ENG",  # EMS12 — coolant temp °C (start_bit=8, length=8, scale=0.75, offset=-48)
        "can_id_b": "0x316", "sig_b": "N",          # EMS11 — engine RPM
        "predicate": lambda temp, rpm: (
            temp > 120.0 and rpm < 200.0,
            f"Coolant {temp:.0f}°C but RPM {rpm:.0f} — overtemp signal while engine off",
        ),
    },
]

_ALIGN_TOLERANCE_MS = 0.1   # 100 ms


def check(df: pd.DataFrame) -> pd.DataFrame:
    """Annotate df with cross-signal contradiction flags.

    Only frames from the relevant CAN IDs are examined; all other rows
    pass through with violation=False.
    """
    out = df.copy()
    out["correlation_violation"] = False
    out["correlation_detail"]    = ""

    if df.empty or "can_id" not in df.columns or "timestamp" not in df.columns:
        return out

    byte_cols = [c for c in ["b0","b1","b2","b3","b4","b5","b6","b7"] if c in df.columns]
    if not byte_cols:
        return out

    def _decode_series(frames: pd.DataFrame, can_id_hex: str, sig: str) -> pd.Series:
        smap = _load_signal_map()
        norm = can_id_hex.upper().lstrip("0X")
        entry = next((v for k, v in smap.items() if k.upper().lstrip("0X") == norm), None)
        if entry is None:
            return pd.Series(np.nan, index=frames.index, dtype=float)
        sig_def = next((s for s in entry.get("signals", []) if s["name"] == sig), None)
        if sig_def is None:
            return pd.Series(np.nan, index=frames.index, dtype=float)

        start_bit = int(sig_def.get("start_bit", 0))
        length = int(sig_def.get("length", 8))
        scale = float(sig_def.get("scale", 1.0))
        offset = float(sig_def.get("offset", 0.0))

        # Assemble an 8-byte little-endian integer per row using numpy — no Python loop
        raw_int = np.zeros(len(frames), dtype=np.uint64)
        for i, col in enumerate(byte_cols):
            col_vals = (
                frames[col].fillna(0).values.astype(np.uint64)
                if col in frames.columns
                else np.zeros(len(frames), dtype=np.uint64)
            )
            raw_int |= col_vals << np.uint64(i * 8)

        mask = np.uint64((1 << length) - 1)
        vals = ((raw_int >> np.uint64(start_bit)) & mask).astype(np.float64) * scale + offset
        return pd.Series(vals, index=frames.index, dtype=float)

    for rule in _RULES:
        cid_a = int(rule["can_id_a"], 16)
        cid_b = int(rule["can_id_b"], 16)

        fa = out[out["can_id"] == cid_a].copy()
        fb = out[out["can_id"] == cid_b].copy()
        if fa.empty or fb.empty:
            continue

        fa["_val"] = _decode_series(fa, rule["can_id_a"], rule["sig_a"])
        fb["_val"] = _decode_series(fb, rule["can_id_b"], rule["sig_b"])
        fa = fa.dropna(subset=["_val"]).sort_values("timestamp")
        fb = fb.dropna(subset=["_val"]).sort_values("timestamp")
        if fa.empty or fb.empty:
            continue

        # Align by nearest timestamp
        merged = pd.merge_asof(
            fa[["timestamp", "_val"]].rename(columns={"_val": "_a"}),
            fb[["timestamp", "_val"]].rename(columns={"_val": "_b"}),
            on="timestamp",
            direction="nearest",
            tolerance=_ALIGN_TOLERANCE_MS,
        ).dropna(subset=["_a", "_b"])

        if merged.empty:
            continue

        # Evaluate predicates once per aligned pair (no row-by-row iterrows)
        pred_out = [
            rule["predicate"](a, b)
            for a, b in zip(merged["_a"].values, merged["_b"].values)
        ]
        for (violated, detail), ts in zip(pred_out, merged["timestamp"].values):
            if violated:
                mask_rows = (out["can_id"] == cid_a) & (out["timestamp"] == ts)
                out.loc[mask_rows, "correlation_violation"] = True
                out.loc[mask_rows, "correlation_detail"]    = detail

    return out
