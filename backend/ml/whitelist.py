"""CAN ID whitelist enforcement.

Builds an allowed set of CAN IDs from the first N seconds of a session
(the "learning window" when the bus is assumed to be clean).
Any frame whose CAN ID never appeared in the learning window is flagged
as an immediate intrusion — no ML model required.

This catches fuzzy / random-ID attacks that the ML may score low because
their *payload bytes* happen to look statistically ordinary.
"""
from __future__ import annotations

import pandas as pd

LEARN_WINDOW_SEC  = 30.0   # seconds of "clean" data used to build the list
MIN_LEARN_FRAMES  = 100    # if fewer frames in window, fall back to full df


def build(df: pd.DataFrame, learn_window_sec: float = LEARN_WINDOW_SEC) -> set[str]:
    """Return a set of hex CAN ID strings seen in the first N seconds.

    Example return value: {'0x316', '0x329', '0x260', ...}
    """
    if df.empty or "timestamp" not in df.columns or "can_id" not in df.columns:
        return set()

    t0 = float(df["timestamp"].min())
    mask = df["timestamp"] <= t0 + learn_window_sec
    learn_df = df[mask]

    if len(learn_df) < MIN_LEARN_FRAMES:
        learn_df = df  # not enough data — trust everything

    return {f"0x{int(cid):03X}" for cid in learn_df["can_id"].unique()}


def check(df: pd.DataFrame, whitelist: set[str], learn_window_sec: float = LEARN_WINDOW_SEC) -> pd.DataFrame:
    """Annotate df with a ``whitelist_violation`` boolean column.

    Frames inside the learning window are never flagged (they built the list).
    Frames after the window whose CAN ID is absent from the whitelist are
    flagged ``True``.

    Adds columns:
        whitelist_violation (bool)
    """
    out = df.copy()

    if not whitelist:
        out["whitelist_violation"] = False
        return out

    hex_ids = out["can_id"].apply(lambda x: f"0x{int(x):03X}")
    unknown = ~hex_ids.isin(whitelist)

    # Never flag the learning window itself
    if "timestamp" in out.columns:
        t0 = float(out["timestamp"].min())
        in_window = out["timestamp"] <= t0 + learn_window_sec
        unknown &= ~in_window

    out["whitelist_violation"] = unknown
    return out


def violations_summary(df: pd.DataFrame) -> list[dict]:
    """Return a compact list of unknown CAN IDs and how many times each appeared."""
    if "whitelist_violation" not in df.columns:
        return []

    bad = df[df["whitelist_violation"]]
    if bad.empty:
        return []

    result = []
    for raw_id, grp in bad.groupby("can_id"):
        result.append({
            "can_id":      f"0x{int(raw_id):03X}",
            "frame_count": len(grp),
            "first_seen":  float(grp["timestamp"].min()),
        })
    return sorted(result, key=lambda x: x["frame_count"], reverse=True)
