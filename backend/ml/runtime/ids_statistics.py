from __future__ import annotations

import csv
import json
import time
from collections import Counter
from pathlib import Path


class IDSStatistics:
    """Collects replay-time operational IDS statistics."""

    def __init__(self, replay_source: Path) -> None:
        self.replay_source = replay_source
        self.started_at = time.perf_counter()
        self.total_frames_processed = 0
        self.total_alerts = 0
        self.alerts_per_severity: Counter[str] = Counter()
        self.alerts_per_reason: Counter[str] = Counter()
        self.alerts_per_can_id: Counter[int] = Counter()
        self.alerts_per_risk_level: Counter[str] = Counter()
        self.max_fusion_score = float("-inf")
        self._fusion_score_sum = 0.0

    def reset(self) -> None:
        self.started_at = time.perf_counter()
        self.total_frames_processed = 0
        self.total_alerts = 0
        self.alerts_per_severity = Counter()
        self.alerts_per_reason = Counter()
        self.alerts_per_can_id = Counter()
        self.alerts_per_risk_level = Counter()
        self.max_fusion_score = float("-inf")
        self._fusion_score_sum = 0.0

    def on_frame(self) -> None:
        self.total_frames_processed += 1

    def on_score(self, fusion_score: float) -> None:
        self.max_fusion_score = max(self.max_fusion_score, float(fusion_score))
        self._fusion_score_sum += float(fusion_score)

    def on_alert(self, alert: dict[str, object]) -> None:
        self.total_alerts += 1
        risk = str(alert.get("risk_level", "UNKNOWN"))
        self.alerts_per_severity[risk] += 1
        self.alerts_per_risk_level[risk] += 1
        self.alerts_per_can_id[int(alert.get("can_id", -1))] += 1

        reason_text = str(alert.get("reason", "unknown"))
        self.alerts_per_reason[self._reason_bucket(reason_text)] += 1

    @staticmethod
    def _reason_bucket(reason_text: str) -> str:
        # Parse the inline reason string emitted by runtime engine and map to dominant cause.
        vals: dict[str, float] = {}
        for part in reason_text.split(","):
            part = part.strip()
            if "=" not in part:
                continue
            k, v = part.split("=", 1)
            try:
                vals[k.strip()] = float(v.strip())
            except ValueError:
                continue
        if not vals:
            return "unknown"
        dominant = max(vals, key=vals.get)
        mapping = {
            "timing": "timing_burst",
            "payload": "continuity_break",
            "ml": "ml_outlier",
            "persistence": "sustained_anomaly",
        }
        return mapping.get(dominant, dominant)

    def as_dict(self) -> dict[str, object]:
        elapsed = max(time.perf_counter() - self.started_at, 1e-9)
        alerts_per_1000 = (self.total_alerts / max(self.total_frames_processed, 1)) * 1000.0
        critical_rate = (self.alerts_per_risk_level.get("CRITICAL", 0) / max(self.total_frames_processed, 1)) * 1000.0
        high_rate = (self.alerts_per_risk_level.get("HIGH", 0) / max(self.total_frames_processed, 1)) * 1000.0
        return {
            "replay_source": str(self.replay_source),
            "total_frames_processed": int(self.total_frames_processed),
            "total_alerts": int(self.total_alerts),
            "alerts_per_1000_frames": float(alerts_per_1000),
            "critical_alert_rate": float(critical_rate),
            "high_alert_rate": float(high_rate),
            "alerts_per_severity": dict(self.alerts_per_severity),
            "alerts_per_reason": dict(self.alerts_per_reason),
            "alerts_per_can_id": {f"0x{k:X}": int(v) for k, v in self.alerts_per_can_id.items() if k >= 0},
            "alerts_per_risk_level": dict(self.alerts_per_risk_level),
            "max_fusion_score_observed": float(self.max_fusion_score if self.total_frames_processed else 0.0),
            "average_fusion_score_observed": float(self._fusion_score_sum / max(self.total_frames_processed, 1)),
            "runtime_duration_sec": float(elapsed),
            "fps": float(self.total_frames_processed / elapsed),
        }

    def print_summary(self, is_normal: bool) -> None:
        d = self.as_dict()
        print("\n====================================================")
        print("IDS REPLAY SUMMARY")
        print("====================================================")
        print(f"Replay source: {d['replay_source']}")
        print(f"Frames processed: {d['total_frames_processed']}")
        print(f"Total alerts: {d['total_alerts']}")
        print(f"Alerts per 1000 frames: {d['alerts_per_1000_frames']:.3f}")
        print(f"MAX SCORE OBSERVED: {d['max_fusion_score_observed']:.6f}")
        print(f"AVERAGE SCORE OBSERVED: {d['average_fusion_score_observed']:.6f}")
        print("\n--- Severity Distribution ---")
        for k in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]:
            print(f"{k}: {self.alerts_per_severity.get(k, 0)}")

        print("\n--- Top Alert Reasons ---")
        for reason, count in self.alerts_per_reason.most_common(5):
            print(f"{reason}: {count}")

        print("\n--- Top CAN IDs ---")
        for cid, count in self.alerts_per_can_id.most_common(5):
            print(f"0x{cid:X}: {count}")

        if is_normal:
            print("\n[NORMAL VALIDATION]")
            if d["alerts_per_1000_frames"] <= 5.0 and self.alerts_per_severity.get("CRITICAL", 0) == 0:
                print("Alert rate acceptable.")
                print("No critical alert storm detected.")
                print("Runtime behavior stable.")
            else:
                print("Alert density unusually high.")
                print("Thresholds may be oversensitive.")
        else:
            dom = self.alerts_per_reason.most_common(1)[0][0] if self.alerts_per_reason else "unknown"
            print("\n[ATTACK VALIDATION]")
            if dom in {"timing_burst", "sustained_anomaly"}:
                print("Dominant detection layer: timing")
                print("Burst anomalies detected rapidly.")
            elif dom in {"continuity_break"}:
                print("Dominant detection layer: payload")
                print("Entropy/continuity instability strongly elevated.")
            else:
                print("Dominant detection layer: hybrid")
                print("Multiple anomaly signals contributed.")

    def save_reports(self, out_dir: Path, stem: str, lightweight: bool = True, alert_records: list | None = None) -> tuple[Path, Path]:
        out_dir.mkdir(parents=True, exist_ok=True)
        jpath = out_dir / f"{stem}_summary.json"
        cpath = out_dir / f"{stem}_summary.csv"
        d = self.as_dict()
        if alert_records:
            d["alert_records"] = alert_records
        jpath.write_text(json.dumps(d, indent=2), encoding="utf-8")

        if not lightweight:
            with cpath.open("w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["metric", "value"])
                w.writerow(["replay_source", d["replay_source"]])
                w.writerow(["total_frames_processed", d["total_frames_processed"]])
                w.writerow(["total_alerts", d["total_alerts"]])
                w.writerow(["alerts_per_1000_frames", f"{d['alerts_per_1000_frames']:.6f}"])
                w.writerow(["critical_alert_rate", f"{d['critical_alert_rate']:.6f}"])
                w.writerow(["high_alert_rate", f"{d['high_alert_rate']:.6f}"])
                w.writerow(["runtime_duration_sec", f"{d['runtime_duration_sec']:.6f}"])
                w.writerow(["fps", f"{d['fps']:.6f}"])
                for k, v in self.alerts_per_severity.items():
                    w.writerow([f"severity_{k}", v])
                for k, v in self.alerts_per_reason.most_common():
                    w.writerow([f"reason_{k}", v])
                for k, v in self.alerts_per_can_id.most_common(20): # Cap at 20 for operational use
                    w.writerow([f"can_id_0x{k:X}", v])
        else:
            # Operational mode only saves a minimal CSV
            with cpath.open("w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["metric", "value"])
                w.writerow(["total_alerts", d["total_alerts"]])
                w.writerow(["max_score", f"{d['max_fusion_score_observed']:.3f}"])
        return jpath, cpath

