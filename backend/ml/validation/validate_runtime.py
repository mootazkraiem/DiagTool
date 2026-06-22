from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--alerts", type=Path, default=Path("backend/ml/outputs/alerts/alerts.csv"))
    p.add_argument("--out", type=Path, default=Path("backend/ml/outputs/validation_reports/runtime_validation.json"))
    return p.parse_args()


def main() -> None:
    args = parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    if not args.alerts.exists():
        report = {"status": "no_alert_file", "alerts": 0}
    else:
        df = pd.read_csv(args.alerts)
        report = {
            "status": "ok",
            "alerts": int(len(df)),
            "risk_counts": df["risk_level"].value_counts().to_dict() if "risk_level" in df.columns else {},
        }
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"[VALIDATE_RUNTIME] {report}")


if __name__ == "__main__":
    main()
