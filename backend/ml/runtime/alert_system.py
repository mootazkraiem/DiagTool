from __future__ import annotations

import csv
import json
from pathlib import Path


class AlertSystem:
    def __init__(self, jsonl_path: Path, csv_path: Path, cooldown_seconds: float = 1.0) -> None:
        self.jsonl_path = jsonl_path
        self.csv_path = csv_path
        self.cooldown_seconds = cooldown_seconds
        self._last_alert_ts_by_id: dict[int, float] = {}
        self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.csv_path.exists():
            with self.csv_path.open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=["timestamp", "can_id", "risk_level", "score", "reason"])
                w.writeheader()

    def should_alert(self, timestamp: float, can_id: int, risk_level: str) -> bool:
        last = self._last_alert_ts_by_id.get(can_id)
        if last is not None and (timestamp - last) < self.cooldown_seconds:
            return False
        self._last_alert_ts_by_id[can_id] = timestamp
        return True

    def emit(self, timestamp: float, can_id: int, risk_level: str, score: float, reason: str) -> dict[str, object]:
        rec = {
            "timestamp": float(timestamp),
            "can_id": int(can_id),
            "risk_level": str(risk_level),
            "score": float(score),
            "reason": str(reason),
        }
        with self.jsonl_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
        with self.csv_path.open("a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["timestamp", "can_id", "risk_level", "score", "reason"])
            w.writerow(rec)
        return rec
