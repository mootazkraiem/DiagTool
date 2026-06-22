"""Build analyst context for the CAN Security Analyst Assistant.

Aggregates four context sources:
  1. Current anomaly — features extracted from alert dict + reason string
  2. Attack KB match — keyword retrieval against attack_kb.json
  3. Historical anomalies — feature cosine similarity from anomaly_history.jsonl
  4. Normal state statistics — per-state expected feature ranges
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_STATE_STATS_PATH = Path(__file__).resolve().parents[2] / "knowledge" / "state_stats.json"
_state_stats_cache: dict[str, Any] | None = None


def _load_state_stats() -> dict[str, Any]:
    global _state_stats_cache
    if _state_stats_cache is None:
        try:
            _state_stats_cache = json.loads(_STATE_STATS_PATH.read_text(encoding="utf-8"))
        except Exception:
            _state_stats_cache = {}
    return _state_stats_cache


def _parse_reason(reason: str) -> tuple[float, float]:
    """Return (frequency_hz, entropy) parsed from reason string."""
    freq = 0.0
    ent = 0.0
    m = re.search(r"freq=([\d.]+)", reason)
    if m:
        freq = float(m.group(1))
    m = re.search(r"can_id_entropy=([\d.]+)", reason)
    if m:
        ent = float(m.group(1))
    return freq, ent


def _deviation_tag(value: float | None, lo: float, hi: float) -> str:
    """Return a human-readable deviation label."""
    if value is None:
        return "unknown"
    if value < lo:
        ratio = lo / value if value > 0 else float("inf")
        return f"{value:.1f} — BELOW NORMAL (expected {lo}–{hi}; ×{ratio:.0f} lower)"
    if value > hi:
        ratio = value / hi if hi > 0 else float("inf")
        return f"{value:.1f} — ABOVE NORMAL (expected {lo}–{hi}; ×{ratio:.0f} higher)"
    return f"{value:.1f} — within normal range ({lo}–{hi})"


def build_context(alert: dict[str, Any]) -> dict[str, Any]:
    """Assemble the full analyst context dict."""
    from backend.ml.explainer.rag import retrieve
    from backend.ml.explainer.anomaly_store import find_similar

    reason = str(alert.get("reason", ""))
    freq, ent = _parse_reason(reason)
    time_diff = round(1.0 / freq, 4) if freq > 0 else None

    anomaly: dict[str, Any] = {
        "can_id":     str(alert.get("can_id", "unknown")),
        "state":      str(alert.get("vehicle_state", alert.get("state", "unknown"))),
        "frequency":  round(freq, 1) if freq else None,
        "entropy":    round(ent, 3) if ent else None,
        "time_diff":  time_diff,
        "score":      round(float(alert.get("score", 0.0)), 3),
        "severity":   str(alert.get("severity", alert.get("risk_level", "UNKNOWN"))),
        "layer":      str(alert.get("dominant_detection_layer", "unknown")),
        "reason":     reason[:300],
    }

    kb = retrieve(alert)
    similar = find_similar(alert, top_k=3)

    state_key = anomaly["state"].lower()
    stats = _load_state_stats()
    state_normal = stats.get(state_key) or stats.get("driving") or {}

    # Pre-compute deviation strings for prompt rendering
    freq_range = state_normal.get("frequency_range", [0, 9999])
    ent_range = state_normal.get("entropy_range", [0, 9999])
    td_range = state_normal.get("time_diff_range", [0, 9999])

    deviations = {
        "frequency": _deviation_tag(anomaly["frequency"], freq_range[0], freq_range[1]),
        "entropy":   _deviation_tag(anomaly["entropy"],   ent_range[0],  ent_range[1]),
        "time_diff": _deviation_tag(anomaly["time_diff"], td_range[0],   td_range[1]),
    }

    return {
        "anomaly":         anomaly,
        "kb":              kb,
        "similar_history": similar,
        "state_normal":    state_normal,
        "state_key":       state_key,
        "deviations":      deviations,
    }
