"""Alert deduplication engine.

Collapses bursts of alerts on the same CAN ID within a short time window
into a single summary entry so the UI doesn't get flooded with thousands
of identical rows during a DoS attack.

A "burst" is >= BURST_THRESHOLD alerts on the same CAN ID within WINDOW_SEC.
The summary carries:
    is_burst_summary  True
    suppressed_count  total frames collapsed
    burst_label       human-readable description
"""
from __future__ import annotations

WINDOW_SEC      = 2.0   # sliding window width
BURST_THRESHOLD = 8     # alerts before collapsing


def deduplicate(contexts: list[dict], window_sec: float = WINDOW_SEC) -> list[dict]:
    """Collapse burst alerts into single summary entries.

    Args:
        contexts:   list of alert context dicts (must have 'can_id' and 'timestamp').
        window_sec: time window for grouping.

    Returns:
        Deduplicated list ordered by timestamp.  Normal alerts pass through
        unchanged; burst alerts are replaced by one summary per window.
    """
    if not contexts:
        return []

    sorted_ctxs = sorted(contexts, key=lambda c: float(c.get("timestamp", 0)))

    # Pass 1: assign every context to a (can_id, window_index) bucket using the
    # same sliding-window rule as before, and tally each bucket's total size and
    # peak score. This is done up front, per can_id independently, so alerts
    # from a *different* CAN ID interleaved in time can never be mistaken for
    # part of this window (unlike a single shared mutable result list).
    state: dict[str, dict] = {}          # can_id -> {window_start, window_index}
    bucket_of: list[tuple] = []          # parallel to sorted_ctxs
    buckets: dict[tuple, dict] = {}      # (can_id, window_index) -> {count, peak_score, first_idx}

    for i, ctx in enumerate(sorted_ctxs):
        can_id = str(ctx.get("can_id", "unknown"))
        ts     = float(ctx.get("timestamp", 0))
        score  = float(ctx.get("anomaly_score", 0))

        st = state.get(can_id)
        if st is None or (ts - st["window_start"]) > window_sec:
            st = {"window_start": ts, "window_index": (st["window_index"] + 1) if st else 0}
            state[can_id] = st

        key = (can_id, st["window_index"])
        bucket_of.append(key)
        bucket = buckets.get(key)
        if bucket is None:
            buckets[key] = {"count": 1, "peak_score": score, "first_idx": i}
        else:
            bucket["count"] += 1
            bucket["peak_score"] = max(bucket["peak_score"], score)

    # Pass 2: emit. Buckets that never exceed BURST_THRESHOLD pass through
    # unchanged; buckets that do are collapsed into a single summary entry,
    # emitted once at the position of the bucket's first (earliest) context.
    result: list[dict] = []
    emitted: set = set()
    for i, ctx in enumerate(sorted_ctxs):
        key = bucket_of[i]
        bucket = buckets[key]

        if bucket["count"] <= BURST_THRESHOLD:
            result.append(ctx)
            continue

        if key in emitted:
            continue
        emitted.add(key)

        can_id = key[0]
        base = sorted_ctxs[bucket["first_idx"]]
        summary = dict(base)
        summary["is_burst_summary"] = True
        summary["suppressed_count"] = bucket["count"]
        summary["anomaly_score"]    = bucket["peak_score"]
        summary["temporal_pattern"] = "dos_burst"
        summary["burst_label"] = (
            f"DoS burst on {can_id} — {bucket['count']} frames in {window_sec:.0f}s"
        )
        result.append(summary)

    return result
