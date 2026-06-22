"""Temporal sequence anomaly detector.

Detects attack patterns that only become visible across time:
- DoS burst: a CAN ID appears at >N times its normal frequency in a window
- Rate spike: the frequency of any ID spikes suddenly within a short window
- Payload freeze: the same payload repeats for many consecutive frames (replay)

Works on top of already-computed feature columns (msg_frequency, burstiness)
so it adds zero re-computation cost.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


WINDOW_SEC = 1.0          # analysis window in seconds
DOS_FREQ_MULTIPLIER = 5.0 # freq must be 5x baseline to be DoS
FREEZE_MIN_REPEATS = 10    # minimum consecutive identical payloads to flag


def _byte_cols(df: pd.DataFrame) -> list[str]:
    return [c for c in ["b0", "b1", "b2", "b3", "b4", "b5", "b6", "b7"] if c in df.columns]


def build_frequency_baseline(df: pd.DataFrame, normal_mask: pd.Series | None = None) -> dict[str, float]:
    """
    Compute the baseline msg_frequency per CAN ID from normal frames.

    Returns: {can_id_hex: mean_frequency}
    """
    if "msg_frequency" not in df.columns or "can_id" not in df.columns:
        return {}

    source = df if normal_mask is None else df[normal_mask]
    if source.empty:
        source = df

    baseline: dict[str, float] = {}
    for raw_id, group in source.groupby("can_id"):
        freq = group["msg_frequency"].replace([np.inf, -np.inf], np.nan).dropna()
        if freq.empty:
            continue
        hex_id = f"0x{int(raw_id):03X}"
        baseline[hex_id] = float(freq.mean())
    return baseline


def detect_patterns(df: pd.DataFrame, freq_baseline: dict[str, float]) -> pd.DataFrame:
    """
    Annotate every row with temporal pattern classification.

    Fully vectorized — no Python for-loops over rows.
    Adds columns:
        temporal_pattern: 'normal' | 'dos_burst' | 'rate_spike' | 'payload_freeze'
        temporal_score:   0.0–1.0 severity of the pattern
    """
    out = df.copy()

    if out.empty:
        out["temporal_pattern"] = "normal"
        out["temporal_score"]   = 0.0
        return out

    patterns = pd.Series("normal", index=out.index)
    t_scores  = pd.Series(0.0,      index=out.index)

    byte_cols  = _byte_cols(df)
    has_bytes  = len(byte_cols) > 0
    has_freq   = "msg_frequency" in df.columns
    has_burst  = "burstiness"    in df.columns

    # ── DoS burst: vectorized frequency check ──────────────────────────────
    if has_freq:
        hex_ids       = out["can_id"].apply(lambda x: f"0x{int(x):03X}")
        base_freq_vec = hex_ids.map(freq_baseline).fillna(0.0)
        freq          = out["msg_frequency"].replace([np.inf, -np.inf], 0.0).fillna(0.0)
        ratio         = (freq / base_freq_vec.clip(lower=1e-9)).clip(upper=50.0)
        dos_mask      = (base_freq_vec > 0) & (freq > base_freq_vec * DOS_FREQ_MULTIPLIER)
        dos_score     = ((ratio - DOS_FREQ_MULTIPLIER) / DOS_FREQ_MULTIPLIER).clip(0.0, 1.0)
        patterns[dos_mask] = "dos_burst"
        t_scores[dos_mask] = dos_score[dos_mask]

    # ── Rate spike: vectorized burstiness check ────────────────────────────
    if has_burst:
        burst      = out["burstiness"].fillna(0.0)
        spike_mask = (patterns == "normal") & (burst > 0.8)
        patterns[spike_mask] = "rate_spike"
        t_scores[spike_mask] = burst[spike_mask].clip(0.0, 1.0)

    # ── Payload freeze: consecutive same-payload count per CAN ID ──────────
    if has_bytes:
        payload_str = out[byte_cols].astype(str).agg("".join, axis=1)

        # Sort by (can_id, timestamp) to get consecutive frames per ID
        sort_idx    = out.sort_values(["can_id", "timestamp"]).index
        payload_srt = payload_str[sort_idx]
        can_id_srt  = out.loc[sort_idx, "can_id"]

        # Mark whether each frame has the same payload as the previous frame
        # from the SAME CAN ID
        prev_payload = payload_srt.groupby(can_id_srt).shift(1)
        is_same      = (payload_srt == prev_payload)

        # Cumsum trick: assign a group-break ID that resets on each payload change
        change_id    = (~is_same).groupby(can_id_srt).cumsum()

        # Count consecutive same-payload frames within each break group
        consec       = change_id.groupby([can_id_srt, change_id]).cumcount() + 1
        # consec is indexed like sort_idx — map back to original index
        consec_orig  = consec.reindex(out.index).fillna(1)

        freeze_mask  = (consec_orig >= FREEZE_MIN_REPEATS) & (patterns == "normal")
        patterns[freeze_mask] = "payload_freeze"
        t_scores[freeze_mask] = (consec_orig[freeze_mask] / 50.0).clip(0.0, 1.0)

    out["temporal_pattern"] = patterns
    out["temporal_score"]   = t_scores.round(4)
    return out


def summarize_anomaly(
    can_id_hex: str,
    temporal_pattern: str,
    temporal_score: float,
    freq_baseline: dict[str, float],
    current_freq: float = 0.0,
) -> dict[str, Any]:
    """
    Build a human-readable temporal summary for one alert.
    """
    if temporal_pattern == "normal":
        return {"temporal_pattern": "normal", "temporal_score": 0.0}

    base = freq_baseline.get(can_id_hex, 0.0)

    if temporal_pattern == "dos_burst":
        ratio = round(current_freq / base, 1) if base > 0 else "?"
        detail = (
            f"Message frequency is {ratio}× above baseline "
            f"({current_freq:.0f} msg/s vs {base:.0f} msg/s normal) — "
            f"consistent with a DoS flood attack on {can_id_hex}."
        )
    elif temporal_pattern == "rate_spike":
        detail = (
            f"Sudden burst of {can_id_hex} frames detected (burstiness score {temporal_score:.2f}) "
            f"— irregular inter-arrival pattern, possible injection."
        )
    elif temporal_pattern == "payload_freeze":
        detail = (
            f"Identical payload repeated continuously on {can_id_hex} "
            f"— consistent with a replay attack or stuck ECU."
        )
    else:
        detail = f"Temporal anomaly detected: {temporal_pattern}."

    return {
        "temporal_pattern": temporal_pattern,
        "temporal_score": round(temporal_score, 3),
        "detail": detail,
    }
