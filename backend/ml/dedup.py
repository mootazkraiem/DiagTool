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

    result: list[dict] = []
    # per can_id: {window_start, count, peak_score, summary_idx}
    state: dict[str, dict] = {}

    for ctx in sorted_ctxs:
        can_id = str(ctx.get("can_id", "unknown"))
        ts     = float(ctx.get("timestamp", 0))
        score  = float(ctx.get("anomaly_score", 0))

        st = state.get(can_id)

        if st is None or (ts - st["window_start"]) > window_sec:
            # New window
            state[can_id] = {
                "window_start": ts,
                "count":        1,
                "peak_score":   score,
                "summary_idx":  None,
            }
            result.append(ctx)
            continue

        st["count"]      += 1
        st["peak_score"]  = max(st["peak_score"], score)

        if st["count"] <= BURST_THRESHOLD:
            result.append(ctx)

        elif st["count"] == BURST_THRESHOLD + 1:
            # Collapse: remove the last BURST_THRESHOLD individual entries
            for _ in range(BURST_THRESHOLD):
                result.pop()

            summary = dict(ctx)
            summary["is_burst_summary"] = True
            summary["suppressed_count"] = st["count"]
            summary["anomaly_score"]    = st["peak_score"]
            summary["temporal_pattern"] = "dos_burst"
            summary["burst_label"] = (
                f"DoS burst on {can_id} — {st['count']} frames in {window_sec:.0f}s"
            )
            result.append(summary)
            st["summary_idx"] = len(result) - 1

        else:
            # Update existing summary in-place
            idx = st["summary_idx"]
            if idx is not None and idx < len(result):
                result[idx]["suppressed_count"] = st["count"]
                result[idx]["burst_label"] = (
                    f"DoS burst on {can_id} — {st['count']} frames in {window_sec:.0f}s"
                )

    return result
