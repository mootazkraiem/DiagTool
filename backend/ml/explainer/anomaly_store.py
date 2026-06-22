"""Historical anomaly store — JSONL-based with feature-vector cosine similarity.

Persists resolved anomalies so the CAN Security Analyst Assistant can find
similar historical cases and include them in its context.

Store location: backend/ml/outputs/anomaly_history.jsonl
Each line is a JSON object with: can_id, state, frequency, entropy, score,
severity, attack_type, timestamp, summary.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

_STORE_PATH = Path(__file__).resolve().parents[2] / "outputs" / "anomaly_history.jsonl"


def _parse_features(alert: dict[str, Any]) -> tuple[float, float]:
    """Extract (frequency_hz, entropy) from the alert reason string."""
    reason = str(alert.get("reason", ""))
    freq = 0.0
    ent = 0.0
    m = re.search(r"freq=([\d.]+)", reason)
    if m:
        freq = float(m.group(1))
    m = re.search(r"can_id_entropy=([\d.]+)", reason)
    if m:
        ent = float(m.group(1))
    return freq, ent


def _feat_vec(entry: dict[str, Any]) -> tuple[float, float, float]:
    """Normalised feature vector so no dimension dominates cosine similarity."""
    freq = min(float(entry.get("frequency", 0.0)) / 2000.0, 1.0)
    ent = min(float(entry.get("entropy", 0.0)) / 8.0, 1.0)
    scr = min(float(entry.get("score", 0.0)), 1.0)
    return (freq, ent, scr)


def _cosine(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na > 0 and nb > 0 else 0.0


def load_all() -> list[dict[str, Any]]:
    if not _STORE_PATH.exists():
        return []
    entries: list[dict[str, Any]] = []
    for line in _STORE_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return entries


def save_anomaly(alert: dict[str, Any], summary: str) -> None:
    """Append a resolved anomaly to the history store."""
    freq, ent = _parse_features(alert)
    entry = {
        "can_id":     str(alert.get("can_id", "")),
        "state":      str(alert.get("vehicle_state", alert.get("state", ""))),
        "frequency":  freq,
        "entropy":    ent,
        "score":      float(alert.get("score", 0.0)),
        "severity":   str(alert.get("severity", alert.get("risk_level", ""))),
        "attack_type": str(alert.get("attack_type", "")),
        "timestamp":  str(alert.get("timestamp", "")),
        "summary":    summary,
    }
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_STORE_PATH, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def find_similar(alert: dict[str, Any], top_k: int = 3) -> list[dict[str, Any]]:
    """Return up to top_k historical anomalies most similar to the given alert."""
    freq, ent = _parse_features(alert)
    query = {"frequency": freq, "entropy": ent, "score": float(alert.get("score", 0.0))}
    q_vec = _feat_vec(query)
    store = load_all()
    if not store:
        return []
    scored = [(e, _cosine(q_vec, _feat_vec(e))) for e in store]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [e for e, sim in scored[:top_k] if sim >= 0.5]
