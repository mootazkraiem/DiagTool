from __future__ import annotations

import argparse
import gc
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
EVAL_ROOT = PROJECT_ROOT / "assets" / "evaluation"
TIMING_ROOT = EVAL_ROOT / "behavioral_timing"
PAYLOAD_ROOT = EVAL_ROOT / "payload_behavior"
FUSION_ROOT = EVAL_ROOT / "fusion"
ATTACKS = ["normal", "DoS", "Fuzzy", "RPM", "gear"]
EPS = 1e-9


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--eval-root", type=Path, default=EVAL_ROOT)
    p.add_argument("--out", type=Path, default=FUSION_ROOT)
    p.add_argument("--method", type=str, default="sigmoid", choices=["sigmoid", "percentile"])
    return p.parse_args()


def _load_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, low_memory=False) if path.exists() else pd.DataFrame()


def _stats(v: np.ndarray) -> dict[str, float]:
    if len(v) == 0:
        return {"median": 0.0, "mad": 1.0, "p90": 0.0, "p95": 0.0, "p99": 0.0}
    med = float(np.median(v))
    mad = float(np.median(np.abs(v - med)))
    return {
        "median": med,
        "mad": max(mad, 1e-6),
        "p90": float(np.quantile(v, 0.90)),
        "p95": float(np.quantile(v, 0.95)),
        "p99": float(np.quantile(v, 0.99)),
    }


def _norm_robust(raw: np.ndarray, st: dict[str, float], method: str) -> np.ndarray:
    z = (raw - st["median"]) / (st["mad"] + EPS)
    z = np.clip(z, -10.0, 30.0)
    if method == "sigmoid":
        return 1.0 / (1.0 + np.exp(-z))
    # percentile-like mapping using robust anchors from normal
    lo, hi = st["p90"], st["p99"]
    if hi <= lo:
        hi = lo + 1e-6
    return np.clip((raw - lo) / (hi - lo), 0.0, 3.0)


def _stage(msg: str, t0: float) -> None:
    print(f"[STEP5] {msg} | elapsed={time.perf_counter()-t0:.2f}s")


def main() -> None:
    args = parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    _stage("Loading timing/payload/ML score sources", t0)

    timing = {k: _load_csv(args.eval_root / "behavioral_timing" / f"timing_scores_{k}.csv") for k in ATTACKS}
    payload = {k: _load_csv(args.eval_root / "payload_behavior" / f"payload_scores_{k}.csv") for k in ATTACKS}
    ml = _load_csv(args.eval_root / "predictions.csv")

    # Use normal-only for calibration
    tn = timing["normal"].copy()
    pn = payload["normal"].copy()
    mn = ml[ml.get("attack_type", pd.Series(dtype=str)).astype(str).str.lower() == "normal"].copy() if not ml.empty else pd.DataFrame()

    t_raw_n = pd.to_numeric(tn.get("timing_score", pd.Series(dtype=float)), errors="coerce").dropna().to_numpy(float)
    p_raw_n = pd.to_numeric(pn.get("payload_behavior_score", pd.Series(dtype=float)), errors="coerce").dropna().to_numpy(float)
    # existing ML score is decision_function-style where lower may indicate anomaly; invert to anomaly-oriented
    m_raw_n = -pd.to_numeric(mn.get("score", pd.Series(dtype=float)), errors="coerce").dropna().to_numpy(float)

    ref = {
        "timing": _stats(t_raw_n),
        "payload": _stats(p_raw_n),
        "ml": _stats(m_raw_n),
        "method": args.method,
    }
    (args.out / "normalization_reference.json").write_text(json.dumps(ref, indent=2), encoding="utf-8")
    _stage("Computed normal-only robust references", t0)

    for split in ATTACKS:
        tdf = timing[split].copy()
        pdf = payload[split].copy()
        if tdf.empty and pdf.empty:
            print(f"[STEP5][WARN] Missing both timing and payload for {split}; skipping")
            continue

        if not tdf.empty:
            tdf["ts_bin"] = (pd.to_numeric(tdf["timestamp"], errors="coerce") * 100).round().astype("Int64")
            tdf["label"] = 0 if split == "normal" else 1
            tdf["attack_type"] = split
        if not pdf.empty:
            pdf["ts_bin"] = (pd.to_numeric(pdf["timestamp"], errors="coerce") * 100).round().astype("Int64")
            pdf["label"] = 0 if split == "normal" else 1
            pdf["attack_type"] = split

        if not tdf.empty and not pdf.empty:
            base = tdf.merge(
                pdf[["attack_type", "label", "can_id", "ts_bin", "payload_behavior_score"]],
                on=["attack_type", "label", "can_id", "ts_bin"],
                how="inner",
            )
        elif not tdf.empty:
            base = tdf.copy()
            base["payload_behavior_score"] = np.nan
        else:
            base = pdf.copy()
            base["timing_score"] = np.nan

        if not ml.empty:
            mm = ml.copy()
            mm["attack_type"] = mm["attack_type"].astype(str)
            mm["ts_bin"] = (pd.to_numeric(mm["timestamp"], errors="coerce") * 100).round().astype("Int64")
            mm = mm.rename(columns={"score": "ml_score_raw", "state": "ml_state", "prediction": "ml_prediction"})
            mm = mm[mm["attack_type"].str.lower() == split.lower()]
            if not mm.empty:
                mm = mm[["attack_type", "label", "ts_bin", "ml_score_raw", "ml_state", "ml_prediction"]].drop_duplicates(["attack_type", "label", "ts_bin"], keep="last")
                base = base.merge(mm, on=["attack_type", "label", "ts_bin"], how="left")
            else:
                base["ml_score_raw"] = np.nan
        else:
            base["ml_score_raw"] = np.nan

        t_raw = pd.to_numeric(base.get("timing_score", pd.Series(dtype=float)), errors="coerce").fillna(ref["timing"]["median"]).to_numpy(float)
        p_raw = pd.to_numeric(base.get("payload_behavior_score", pd.Series(dtype=float)), errors="coerce").fillna(ref["payload"]["median"]).to_numpy(float)
        m_raw = -pd.to_numeric(base.get("ml_score_raw", pd.Series(dtype=float)), errors="coerce").fillna(ref["ml"]["median"]).to_numpy(float)

        base["timing_norm_score"] = _norm_robust(t_raw, ref["timing"], args.method)
        base["payload_norm_score"] = _norm_robust(p_raw, ref["payload"], args.method)
        base["ml_norm_score"] = _norm_robust(m_raw, ref["ml"], args.method)

        outp = args.out / f"normalized_scores_{split}.csv"
        base.to_csv(outp, index=False)
        print(f"[STEP5] Saved {split}: rows={len(base):,} -> {outp}")
        del base
        gc.collect()

    _stage("Done", t0)


if __name__ == "__main__":
    main()
