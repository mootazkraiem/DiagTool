from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import confusion_matrix

PROJECT_ROOT = Path(__file__).resolve().parents[3]
EVAL_ROOT = PROJECT_ROOT / "assets" / "evaluation"
FUSION_ROOT = EVAL_ROOT / "fusion"
ATTACKS = ["DoS", "Fuzzy", "RPM", "gear"]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--in-root", type=Path, default=FUSION_ROOT)
    p.add_argument("--out", type=Path, default=FUSION_ROOT)
    p.add_argument("--w-timing", type=float, default=0.35)
    p.add_argument("--w-payload", type=float, default=0.35)
    p.add_argument("--w-ml", type=float, default=0.20)
    p.add_argument("--w-temporal", type=float, default=0.10)
    return p.parse_args()


def _metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    return {
        "precision": float(tp / max(tp + fp, 1)),
        "recall": float(tp / max(tp + fn, 1)),
        "f1": float((2 * tp) / max(2 * tp + fp + fn, 1)),
        "fpr": float(fp / max(fp + tn, 1)),
        "tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp),
    }


def main() -> None:
    args = parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    print(f"[STEP7] Loading temporal score files | elapsed={time.perf_counter()-t0:.2f}s")

    frames = []
    for split in ["normal", *ATTACKS]:
        p = args.in_root / f"temporal_scores_{split}.csv"
        if not p.exists():
            print(f"[STEP7][WARN] Missing {p}")
            continue
        df = pd.read_csv(p, low_memory=False)
        if df.empty:
            continue
        df["attack_type"] = split
        df["label"] = 0 if split == "normal" else 1
        frames.append(df)
    if not frames:
        print("[STEP7] No temporal inputs found.")
        return

    df = pd.concat(frames, ignore_index=True)
    for c in ["timing_norm_score", "payload_norm_score", "ml_norm_score", "sustained_dominance_score"]:
        df[c] = pd.to_numeric(df.get(c, pd.Series(dtype=float)), errors="coerce").fillna(0.0)

    wsum = args.w_timing + args.w_payload + args.w_ml + args.w_temporal
    wt, wp, wm, wtmp = args.w_timing / wsum, args.w_payload / wsum, args.w_ml / wsum, args.w_temporal / wsum
    df["fusion_timing_contrib"] = wt * df["timing_norm_score"]
    df["fusion_payload_contrib"] = wp * df["payload_norm_score"]
    df["fusion_ml_contrib"] = wm * df["ml_norm_score"]
    df["fusion_temporal_contrib"] = wtmp * df["sustained_dominance_score"]
    df["fusion_score"] = df[["fusion_timing_contrib", "fusion_payload_contrib", "fusion_ml_contrib", "fusion_temporal_contrib"]].sum(axis=1)

    normal = df[df["label"] == 0]
    ths = {
        "p95": float(np.quantile(normal["fusion_score"], 0.95)),
        "p97": float(np.quantile(normal["fusion_score"], 0.97)),
        "p99": float(np.quantile(normal["fusion_score"], 0.99)),
        "p995": float(np.quantile(normal["fusion_score"], 0.995)),
    }

    rows = []
    best_key, best_score = None, -1.0
    for k, th in ths.items():
        dft = df.copy()
        dft["pred"] = (dft["fusion_score"] > th).astype(int)
        m_all = _metrics(dft["label"].to_numpy(int), dft["pred"].to_numpy(int))
        per_attack = {}
        for atk in ATTACKS:
            s = dft[dft["attack_type"].isin(["normal", atk])]
            if s.empty:
                continue
            per_attack[atk] = _metrics(s["label"].to_numpy(int), s["pred"].to_numpy(int))
        rows.append({"threshold_key": k, "threshold": th, **m_all, "per_attack": per_attack})
        score = (m_all["recall"] * (1.0 - m_all["fpr"]))
        if score > best_score:
            best_score = score
            best_key = k

    best_th = ths[best_key]
    df["fusion_prediction"] = (df["fusion_score"] > best_th).astype(int)
    df["dominant_contributor"] = df[["fusion_timing_contrib", "fusion_payload_contrib", "fusion_ml_contrib", "fusion_temporal_contrib"]].idxmax(axis=1)

    df.to_csv(args.out / "hybrid_fusion_scores.csv", index=False)
    (args.out / "threshold_summary.json").write_text(
        json.dumps({
            "threshold_candidates": ths,
            "selected_threshold_key": best_key,
            "selected_threshold": best_th,
            "weights": {"timing": wt, "payload": wp, "ml": wm, "temporal": wtmp},
            "evaluation": rows,
        }, indent=2),
        encoding="utf-8",
    )
    print(f"[STEP7] Done | rows={len(df):,} | best_threshold={best_key}:{best_th:.6f} | elapsed={time.perf_counter()-t0:.2f}s")


if __name__ == "__main__":
    main()
