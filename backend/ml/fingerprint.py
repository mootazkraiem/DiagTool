"""ECU Timing Fingerprinter.

Each legitimate ECU broadcasts its messages on a fixed cycle (e.g. EMS11
every 10 ms). An attacker injecting spoofed frames breaks that rhythm.
This module builds a per-CAN-ID inter-frame interval (IFI) baseline from
the normal portion of the data, then scores every frame by how far its IFI
deviates from that baseline in standard deviations (sigma).

A score > 3.0 sigma is flagged as a timing anomaly.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


# Sigma threshold above which timing is considered anomalous
TIMING_SIGMA_THRESHOLD = 3.0

# Minimum number of normal samples needed to build a reliable baseline
MIN_BASELINE_SAMPLES = 5


def build_baseline(df: pd.DataFrame, normal_mask: pd.Series | None = None) -> dict[str, dict]:
    """
    Compute mean and std of inter-frame intervals per CAN ID.

    Args:
        df: DataFrame with columns [timestamp, can_id].
        normal_mask: Boolean mask selecting the normal (non-anomalous) rows.
                     If None, uses the full DataFrame.

    Returns:
        {can_id_hex: {'mean_ifi': float, 'std_ifi': float, 'samples': int}}
    """
    if df.empty or "timestamp" not in df.columns or "can_id" not in df.columns:
        return {}

    source = df if normal_mask is None else df[normal_mask]
    if source.empty:
        source = df  # fallback: use everything

    baseline: dict[str, dict] = {}
    for raw_id, group in source.groupby("can_id"):
        if len(group) < MIN_BASELINE_SAMPLES:
            continue
        timestamps = group["timestamp"].sort_values().values.astype(float)
        ifis = np.diff(timestamps)
        if len(ifis) < 2:
            continue
        mean_ifi = float(np.mean(ifis))
        std_ifi = float(np.std(ifis))
        if std_ifi < 1e-9:
            std_ifi = mean_ifi * 0.01 or 1e-6  # avoid division by zero
        hex_id = f"0x{int(raw_id):03X}"
        baseline[hex_id] = {
            "mean_ifi": mean_ifi,
            "std_ifi": std_ifi,
            "samples": len(ifis),
        }
    return baseline


def score_frame(can_id_hex: str, ifi: float, baseline: dict[str, dict]) -> float:
    """
    Score a single frame's inter-frame interval against its ECU baseline.

    Returns sigma deviation (0 = perfectly on schedule, >3 = suspicious).
    Returns 0.0 if no baseline exists for this CAN ID.
    """
    entry = baseline.get(can_id_hex)
    if entry is None:
        return 0.0
    std = entry["std_ifi"]
    if std < 1e-9:
        return 0.0
    return abs(ifi - entry["mean_ifi"]) / std


def annotate(df: pd.DataFrame, baseline: dict[str, dict]) -> pd.DataFrame:
    """
    Add 'timing_score' and 'timing_anomaly' columns to df.

    Fully vectorized — no Python for-loops over rows.
    timing_score: sigma deviation for each frame (0 = on-schedule, >3 = suspicious).
    timing_anomaly: True if score > TIMING_SIGMA_THRESHOLD.
    """
    if df.empty:
        out = df.copy()
        out["timing_score"]   = 0.0
        out["timing_anomaly"] = False
        return out

    out = df.copy()

    # Sort by (can_id, timestamp) to compute per-ID inter-frame intervals
    sorted_df = out.sort_values(["can_id", "timestamp"])

    # Per-CAN-ID time diff (vectorized)
    ifi = sorted_df.groupby("can_id")["timestamp"].diff()   # NaN for first frame per ID

    # Map baseline mean/std onto each row
    mean_map = {k: v["mean_ifi"]             for k, v in baseline.items()}
    std_map  = {k: max(v["std_ifi"], 1e-9)   for k, v in baseline.items()}

    hex_ids     = sorted_df["can_id"].apply(lambda x: f"0x{int(x):03X}")
    mean_series = hex_ids.map(mean_map)
    std_series  = hex_ids.map(std_map)

    sigma = ((ifi - mean_series).abs() / std_series).fillna(0.0).clip(lower=0.0)

    # Write back aligned by index (sort_values preserves original index)
    out["timing_score"]   = sigma.round(4)
    out["timing_anomaly"] = sigma > TIMING_SIGMA_THRESHOLD

    # Restore original row order
    out = out.sort_index()
    out["timing_score"]   = out["timing_score"].fillna(0.0)
    out["timing_anomaly"] = out["timing_anomaly"].fillna(False)
    return out


def summarize_anomaly(can_id_hex: str, timing_score: float, baseline: dict[str, dict]) -> dict[str, Any]:
    """
    Build a human-readable fingerprint summary for one alert.
    """
    entry = baseline.get(can_id_hex)
    if entry is None or timing_score < TIMING_SIGMA_THRESHOLD:
        return {"timing_anomaly": False, "timing_score": round(timing_score, 2)}

    mean_ms = entry["mean_ifi"] * 1000
    return {
        "timing_anomaly": True,
        "timing_score": round(timing_score, 2),
        "expected_cycle_ms": round(mean_ms, 2),
        "detail": (
            f"Frame arrived {timing_score:.1f}σ outside expected "
            f"{mean_ms:.1f} ms cycle — possible ECU impersonation or injection."
        ),
    }
