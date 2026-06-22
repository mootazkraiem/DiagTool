from __future__ import annotations

import argparse
import gc
import time
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
EVAL_ROOT = PROJECT_ROOT / "assets" / "evaluation"
FUSION_ROOT = EVAL_ROOT / "fusion"
ATTACKS = ["normal", "DoS", "Fuzzy", "RPM", "gear"]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--in-root", type=Path, default=FUSION_ROOT)
    p.add_argument("--out", type=Path, default=FUSION_ROOT)
    return p.parse_args()


def _stage(msg: str, t0: float) -> None:
    print(f"[STEP6] {msg} | elapsed={time.perf_counter()-t0:.2f}s")


def main() -> None:
    args = parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    short_w, med_w, long_w = 20, 50, 100

    for split in ATTACKS:
        inp = args.in_root / f"normalized_scores_{split}.csv"
        if not inp.exists():
            print(f"[STEP6][WARN] Missing input for {split}: {inp}")
            continue
        df = pd.read_csv(inp, low_memory=False)
        if df.empty:
            continue

        _stage(f"Processing {split} (rows={len(df):,})", t0)
        df["timestamp"] = pd.to_numeric(df.get("timestamp", pd.Series(dtype=float)), errors="coerce")
        df["can_id"] = pd.to_numeric(df.get("can_id", pd.Series(dtype=float)), errors="coerce").fillna(-1).astype(int)
        df = df.sort_values(["can_id", "timestamp"]).reset_index(drop=True)

        for col in ["timing_norm_score", "payload_norm_score", "ml_norm_score"]:
            df[col] = pd.to_numeric(df.get(col, pd.Series(dtype=float)), errors="coerce").fillna(0.0)

        # short/medium/long rolling means/maxima
        g = df.groupby("can_id", sort=False)
        for w, tag in [(short_w, "s"), (med_w, "m"), (long_w, "l")]:
            df[f"timing_mean_{tag}"] = g["timing_norm_score"].transform(lambda s: s.rolling(w, min_periods=1).mean())
            df[f"timing_max_{tag}"] = g["timing_norm_score"].transform(lambda s: s.rolling(w, min_periods=1).max())
            df[f"payload_mean_{tag}"] = g["payload_norm_score"].transform(lambda s: s.rolling(w, min_periods=1).mean())
            df[f"payload_max_{tag}"] = g["payload_norm_score"].transform(lambda s: s.rolling(w, min_periods=1).max())
            df[f"ml_mean_{tag}"] = g["ml_norm_score"].transform(lambda s: s.rolling(w, min_periods=1).mean())
            df[f"ml_max_{tag}"] = g["ml_norm_score"].transform(lambda s: s.rolling(w, min_periods=1).max())

        # temporal persistence metrics
        df["base_anom"] = ((df["timing_norm_score"] > 0.8) | (df["payload_norm_score"] > 0.8) | (df["ml_norm_score"] > 0.8)).astype(int)
        df["anomaly_persistence_ratio"] = g["base_anom"].transform(lambda s: s.rolling(long_w, min_periods=1).mean())
        grp = (df["base_anom"] != g["base_anom"].shift(1)).cumsum()
        df["consecutive_anomaly_streak"] = df["base_anom"].groupby(grp).cumsum()
        df.loc[df["base_anom"] == 0, "consecutive_anomaly_streak"] = 0
        df["anomaly_density"] = g["base_anom"].transform(lambda s: s.rolling(med_w, min_periods=1).mean())
        df["burst_persistence"] = g["base_anom"].transform(lambda s: s.rolling(short_w, min_periods=1).sum()) / float(short_w)
        df["sustained_dominance_score"] = (
            0.4 * df["anomaly_persistence_ratio"]
            + 0.2 * np.clip(df["consecutive_anomaly_streak"] / float(short_w), 0.0, 1.0)
            + 0.2 * df["anomaly_density"]
            + 0.2 * df["burst_persistence"]
        )

        outp = args.out / f"temporal_scores_{split}.csv"
        df.to_csv(outp, index=False)
        print(f"[STEP6] Saved {split}: rows={len(df):,} -> {outp}")
        del df
        gc.collect()

    _stage("Done", t0)


if __name__ == "__main__":
    main()
