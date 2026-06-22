"""Alert grouper and incident engine.

Groups raw per-frame alerts into higher-level security incidents and
generates a recommended response action for each incident.

An incident is a cluster of alerts on the same CAN ID within a
short time window that share the same dominant attack pattern.
"""
from __future__ import annotations

import uuid
from typing import Any


GROUPING_WINDOW_SEC = 2.0   # alerts within this window → same incident
CRITICAL_SCORE = 0.75       # anomaly_score above this → CRITICAL incident
HIGH_SCORE = 0.55


# ── Response recommendation table ─────────────────────────────────────────────

_RESPONSES: dict[str, str] = {
    "dos_burst": (
        "ISOLATE — Rate-limit {can_id}: suspend frames exceeding "
        "normal frequency. Log all source timestamps for forensic review."
    ),
    "payload_freeze": (
        "INVESTIGATE — Replay attack suspected on {can_id}. "
        "Verify ECU liveness via challenge-response if hardware permits."
    ),
    "rate_spike": (
        "MONITOR — Sudden burst on {can_id} detected. "
        "Watch for escalation to sustained DoS flood."
    ),
    "rpm_spoof": (
        "ALERT — Engine RPM spoofing detected on {can_id}. "
        "Cross-validate against ignition timing and throttle position signals."
    ),
    "fuzzy_payload": (
        "QUARANTINE — Unrecognised payload pattern on {can_id}. "
        "Flag bus segment for traffic capture and offline analysis."
    ),
    "plausibility": (
        "FLAG — Signal values outside physical limits on {can_id}. "
        "Verify ECU hardware integrity; possible sensor fault or value injection."
    ),
    "timing": (
        "FINGERPRINT ALERT — {can_id} broke its expected transmission cycle. "
        "Possible ECU impersonation; compare sender electrical signature."
    ),
    "default": (
        "REVIEW — Anomalous activity on {can_id}. "
        "Capture full frame sequence and escalate for forensic analysis."
    ),
}


def _choose_response(can_id: str, dominant_pattern: str, severity: str) -> str:
    template = _RESPONSES.get(dominant_pattern, _RESPONSES["default"])
    response = template.format(can_id=can_id)
    if severity == "CRITICAL":
        response = "⚠ CRITICAL — " + response
    return response


def _dominant_pattern(alerts: list[dict]) -> str:
    """Pick the most common non-normal temporal/attack pattern in a group."""
    counts: dict[str, int] = {}
    for a in alerts:
        p = a.get("temporal_pattern", "normal")
        if p != "normal":
            counts[p] = counts.get(p, 0) + 1
        kb = a.get("kb_match", "")
        if kb and kb != "unknown":
            counts[kb] = counts.get(kb, 0) + 1
        if not a.get("plausibility_passed", True):
            counts["plausibility"] = counts.get("plausibility", 0) + 1
        if a.get("timing_anomaly", False):
            counts["timing"] = counts.get("timing", 0) + 1

    return max(counts, key=counts.get) if counts else "default"


def _severity(peak_score: float, frame_count: int) -> str:
    if peak_score >= CRITICAL_SCORE or frame_count >= 100:
        return "CRITICAL"
    if peak_score >= HIGH_SCORE or frame_count >= 20:
        return "HIGH"
    return "WARNING"


def group(alerts: list[dict], window_sec: float = GROUPING_WINDOW_SEC) -> list[dict]:
    """
    Group raw alert dicts into security incidents.

    Args:
        alerts: list of alert context dicts from engine.build_anomaly_context()
                enriched with plausibility/timing/temporal fields.
        window_sec: merge alerts within this time span (same CAN ID).

    Returns:
        List of incident dicts ordered by first_seen ascending.
    """
    if not alerts:
        return []

    # Sort by timestamp
    sorted_alerts = sorted(alerts, key=lambda a: float(a.get("timestamp", 0.0)))

    incidents: list[dict] = []
    # active_groups: can_id_hex -> current open incident dict + member alerts
    active: dict[str, dict] = {}

    for alert in sorted_alerts:
        can_id = str(alert.get("can_id", "unknown"))
        ts = float(alert.get("timestamp", 0.0))
        score = float(alert.get("anomaly_score", 0.0))

        if can_id in active:
            grp = active[can_id]
            if ts - grp["_last_ts"] <= window_sec:
                # Extend the current incident
                grp["_alerts"].append(alert)
                grp["_last_ts"] = ts
                grp["last_seen"] = ts
                grp["frame_count"] += 1
                grp["peak_score"] = max(grp["peak_score"], score)
                continue
            else:
                # Close and emit the old incident
                _finalise(grp, incidents)

        # Open a new incident
        active[can_id] = {
            "incident_id": str(uuid.uuid4())[:8],
            "can_id": can_id,
            "first_seen": ts,
            "last_seen": ts,
            "frame_count": 1,
            "peak_score": score,
            "_last_ts": ts,
            "_alerts": [alert],
        }

    # Close all remaining open incidents
    for grp in active.values():
        _finalise(grp, incidents)

    return sorted(incidents, key=lambda i: i["first_seen"])


def _finalise(grp: dict, out: list[dict]) -> None:
    alerts = grp.pop("_alerts", [])
    grp.pop("_last_ts", None)

    dominant = _dominant_pattern(alerts)
    sev = _severity(grp["peak_score"], grp["frame_count"])
    duration = round(grp["last_seen"] - grp["first_seen"], 3)

    grp["duration_sec"] = duration
    grp["severity"] = sev
    grp["dominant_pattern"] = dominant
    grp["recommended_response"] = _choose_response(grp["can_id"], dominant, sev)

    # Attach top-3 representative alert summaries
    grp["sample_alerts"] = [
        {
            "timestamp": a.get("timestamp"),
            "anomaly_score": round(float(a.get("anomaly_score", 0)), 3),
            "top_feature": a.get("top_feature", ""),
            "temporal_pattern": a.get("temporal_pattern", "normal"),
            "plausibility_passed": a.get("plausibility_passed", True),
            "timing_anomaly": a.get("timing_anomaly", False),
        }
        for a in alerts[:3]
    ]

    out.append(grp)
