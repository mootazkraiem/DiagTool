from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--alerts", type=Path, default=Path("backend/ml/outputs/alerts/alerts.csv"))
    p.add_argument("--replay", type=Path, required=True)
    p.add_argument("--out", type=Path, default=Path("backend/ml/outputs/validation_reports/attack_validation.json"))
    return p.parse_args()


def main() -> None:
    args = parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    replay = pd.read_csv(args.replay)
    alert_count = 0
    if args.alerts.exists():
        alert_count = len(pd.read_csv(args.alerts))
    attacks = int((replay.get("attack_type", pd.Series(dtype=str)).astype(str) != "none").sum()) if "attack_type" in replay.columns else 0
    report = {"attack_frames": attacks, "alerts": int(alert_count), "detection_rate_proxy": float(alert_count / max(attacks, 1))}
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"[VALIDATE_ATTACKS] {report}")


if __name__ == "__main__":
    main()
