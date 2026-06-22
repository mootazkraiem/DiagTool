from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--sim", type=Path, required=True)
    p.add_argument("--out", type=Path, default=Path("backend/ml/outputs/validation_reports/simulator_validation.json"))
    return p.parse_args()


def main() -> None:
    args = parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(args.sim)
    dt = pd.to_numeric(df["timestamp"], errors="coerce").diff().dropna()
    report = {
        "rows": int(len(df)),
        "dt_mean": float(dt.mean()) if len(dt) else 0.0,
        "dt_std": float(dt.std()) if len(dt) else 0.0,
        "can_ids": int(df["can_id"].nunique()) if "can_id" in df.columns else 0,
    }
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"[VALIDATE_SIM] {report}")


if __name__ == "__main__":
    main()
