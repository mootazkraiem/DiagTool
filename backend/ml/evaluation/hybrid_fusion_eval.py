from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import auc, confusion_matrix, precision_recall_curve, roc_curve


PROJECT_ROOT = Path(__file__).resolve().parents[3]
EVAL_ROOT = PROJECT_ROOT / "assets" / "evaluation"
TIMING_ROOT = EVAL_ROOT / "behavioral_timing"
PAYLOAD_ROOT = EVAL_ROOT / "payload_behavior"
OUT_ROOT = EVAL_ROOT / "hybrid_fusion"
ATTACKS = ["DoS", "Fuzzy", "RPM", "gear"]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--eval-root", type=Path, default=EVAL_ROOT)
    p.add_argument("--out", type=Path, default=OUT_ROOT)
    p.add_argument("--w-timing", type=float, default=0.5)
    p.add_argument("--w-payload", type=float, default=0.3)
    p.add_argument("--w-ml", type=float, default=0.2)
    return p.parse_args()


def _load_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, low_memory=False) if path.exists() else pd.DataFrame()


def load_scores(eval_root: Path) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame], pd.DataFrame]:
    timing_root = eval_root / "behavioral_timing"
    payload_root = eval_root / "payload_behavior"
    timing = {}
    payload = {}
    for a in ["normal", *ATTACKS]:
        timing[a] = _load_csv(timing_root / f"timing_scores_{a}.csv")
        payload[a] = _load_csv(payload_root / f"payload_scores_{a}.csv")
    ml = _load_csv(eval_root / "predictions.csv")
    return timing, payload, ml


def normalize_by_normal_p99(normal_vals: np.ndarray, vals: np.ndarray) -> np.ndarray:
    p99 = float(np.quantile(normal_vals, 0.99)) if len(normal_vals) else 1.0
    p99 = max(p99, 1e-9)
    out = vals / p99
    return np.clip(out, 0.0, 10.0)


def pair_corr(df: pd.DataFrame, a: str, b: str) -> float:
    s = df[[a, b]].dropna()
    if len(s) < 5:
        return float("nan")
    return float(s[a].corr(s[b]))


def metric_curves(y_true: np.ndarray, score: np.ndarray, pred: np.ndarray) -> dict[str, float]:
    tn, fp, fn, tp = confusion_matrix(y_true, pred, labels=[0, 1]).ravel()
    fpr, tpr, _ = roc_curve(y_true, score)
    p, r, _ = precision_recall_curve(y_true, score)
    return {
        "precision": float(tp / max(tp + fp, 1)),
        "recall": float(tp / max(tp + fn, 1)),
        "f1": float((2 * tp) / max(2 * tp + fp + fn, 1)),
        "fpr": float(fp / max(fp + tn, 1)),
        "roc_auc": float(auc(fpr, tpr)),
        "pr_auc": float(auc(r, p)),
        "tn": int(tn),
        "fp": int(fp),
        "fn": int(fn),
        "tp": int(tp),
    }


def build_unified(timing: dict[str, pd.DataFrame], payload: dict[str, pd.DataFrame], ml: pd.DataFrame) -> pd.DataFrame:
    # align by attack + timestamp + can_id when possible
    rows = []
    for split in ["normal", *ATTACKS]:
        t = timing.get(split, pd.DataFrame()).copy()
        p = payload.get(split, pd.DataFrame()).copy()
        if t.empty or p.empty:
            continue
        t["attack_type"] = split
        p["attack_type"] = split
        t["label"] = 0 if split == "normal" else 1
        p["label"] = 0 if split == "normal" else 1
        t["ts_bin"] = (pd.to_numeric(t["timestamp"], errors="coerce") * 100).round().astype("Int64")
        p["ts_bin"] = (pd.to_numeric(p["timestamp"], errors="coerce") * 100).round().astype("Int64")
        j = t.merge(
            p[["attack_type", "label", "can_id", "ts_bin", "payload_behavior_score"]],
            on=["attack_type", "label", "can_id", "ts_bin"],
            how="inner",
        )
        if not j.empty:
            rows.append(j)
    base = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    if base.empty:
        return base
    base = base.rename(columns={"timing_score": "timing_score_raw"})
    # attach ML by nearest ts/state-level artifact (ml has no can_id)
    if not ml.empty and "score" in ml.columns and "attack_type" in ml.columns:
        mm = ml.copy()
        mm["ts_bin"] = (pd.to_numeric(mm["timestamp"], errors="coerce") * 100).round().astype("Int64")
        mm["attack_type"] = mm["attack_type"].astype(str)
        mm = mm.rename(columns={"score": "ml_score_raw"})
        base = base.merge(mm[["attack_type", "label", "ts_bin", "ml_score_raw", "prediction"]], on=["attack_type", "label", "ts_bin"], how="left")
    return base


def main() -> None:
    args = parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    plots = args.out / "plots"
    plots.mkdir(parents=True, exist_ok=True)

    timing, payload, ml = load_scores(args.eval_root)
    df = build_unified(timing, payload, ml)
    if df.empty:
        print("No unified score data available for fusion eval.")
        return

    # 8.0A correlation analysis
    corr_rows = []
    for split in ["normal", *ATTACKS]:
        s = df[df["attack_type"] == split]
        corr_rows.append(
            {
                "split": split,
                "corr_timing_payload": pair_corr(s, "timing_score_raw", "payload_behavior_score"),
                "corr_timing_ml": pair_corr(s, "timing_score_raw", "ml_score_raw"),
                "corr_payload_ml": pair_corr(s, "payload_behavior_score", "ml_score_raw"),
            }
        )
    corr_df = pd.DataFrame(corr_rows)

    # 8.1 percentile normalization on normal only
    n = df[df["label"] == 0]
    df["timing_norm"] = normalize_by_normal_p99(n["timing_score_raw"].dropna().to_numpy(float), pd.to_numeric(df["timing_score_raw"], errors="coerce").fillna(0).to_numpy(float))
    df["payload_norm"] = normalize_by_normal_p99(n["payload_behavior_score"].dropna().to_numpy(float), pd.to_numeric(df["payload_behavior_score"], errors="coerce").fillna(0).to_numpy(float))
    ml_raw = -pd.to_numeric(df["ml_score_raw"], errors="coerce").fillna(0).to_numpy(float)
    ml_n = -pd.to_numeric(n["ml_score_raw"], errors="coerce").fillna(0).to_numpy(float)
    df["ml_norm"] = normalize_by_normal_p99(ml_n, ml_raw)

    # 8.2A controlled weighted fusion (configurable)
    wt, wp, wm = float(args.w_timing), float(args.w_payload), float(args.w_ml)
    wsum = max(wt + wp + wm, 1e-9)
    wt, wp, wm = wt / wsum, wp / wsum, wm / wsum
    df["fused_score"] = wt * df["timing_norm"] + wp * df["payload_norm"] + wm * df["ml_norm"]

    # per-family predictions with normal p99 threshold (no aggressive tuning)
    th_t = float(np.quantile(df[df["label"] == 0]["timing_norm"], 0.99))
    th_p = float(np.quantile(df[df["label"] == 0]["payload_norm"], 0.99))
    th_m = float(np.quantile(df[df["label"] == 0]["ml_norm"], 0.99))
    th_f = float(np.quantile(df[df["label"] == 0]["fused_score"], 0.99))
    df["pred_timing"] = (df["timing_norm"] > th_t).astype(int)
    df["pred_payload"] = (df["payload_norm"] > th_p).astype(int)
    df["pred_ml"] = (df["ml_norm"] > th_m).astype(int)
    df["pred_fused"] = (df["fused_score"] > th_f).astype(int)

    # 8.0B dominance matrix
    dom_rows = []
    for split in ATTACKS:
        s = df[df["attack_type"] == split]
        if s.empty:
            continue
        means = {
            "timing": float(s["timing_norm"].mean()),
            "payload": float(s["payload_norm"].mean()),
            "ml": float(s["ml_norm"].mean()),
        }
        winner = max(means, key=means.get)
        dom_rows.append({"attack": split, **means, "dominant_family": winner})
    dom_df = pd.DataFrame(dom_rows)

    # 8.0C false-positive overlap
    ndf = df[df["label"] == 0].copy()
    fp_t = set(ndf.index[ndf["pred_timing"] == 1].tolist())
    fp_p = set(ndf.index[ndf["pred_payload"] == 1].tolist())
    fp_m = set(ndf.index[ndf["pred_ml"] == 1].tolist())
    fp_overlap = {
        "fp_timing": len(fp_t),
        "fp_payload": len(fp_p),
        "fp_ml": len(fp_m),
        "fp_tp_intersection": len(fp_t & fp_p),
        "fp_tm_intersection": len(fp_t & fp_m),
        "fp_pm_intersection": len(fp_p & fp_m),
        "fp_all_three": len(fp_t & fp_p & fp_m),
    }

    # 8.3 comparative validation
    y = df["label"].to_numpy(int)
    comp = {
        "timing_only": metric_curves(y, df["timing_norm"].to_numpy(float), df["pred_timing"].to_numpy(int)),
        "payload_only": metric_curves(y, df["payload_norm"].to_numpy(float), df["pred_payload"].to_numpy(int)),
        "ml_only": metric_curves(y, df["ml_norm"].to_numpy(float), df["pred_ml"].to_numpy(int)),
        "fused": metric_curves(y, df["fused_score"].to_numpy(float), df["pred_fused"].to_numpy(int)),
    }

    # per-attack fused metrics
    per_attack = []
    for split in ATTACKS:
        s = pd.concat([df[df["attack_type"] == "normal"], df[df["attack_type"] == split]], ignore_index=True)
        if s.empty:
            continue
        yy = s["label"].to_numpy(int)
        per_attack.append(
            {
                "attack": split,
                "timing_f1": metric_curves(yy, s["timing_norm"].to_numpy(float), s["pred_timing"].to_numpy(int))["f1"],
                "payload_f1": metric_curves(yy, s["payload_norm"].to_numpy(float), s["pred_payload"].to_numpy(int))["f1"],
                "ml_f1": metric_curves(yy, s["ml_norm"].to_numpy(float), s["pred_ml"].to_numpy(int))["f1"],
                "fused_f1": metric_curves(yy, s["fused_score"].to_numpy(float), s["pred_fused"].to_numpy(int))["f1"],
            }
        )
    per_attack_df = pd.DataFrame(per_attack)

    # 8.4 explainability prep
    def explain_row(r: pd.Series) -> str:
        parts = sorted(
            [("timing", r["timing_norm"]), ("payload", r["payload_norm"]), ("ml", r["ml_norm"])],
            key=lambda x: x[1],
            reverse=True,
        )
        lvl = "HIGH" if r["fused_score"] > th_f * 1.5 else ("MEDIUM" if r["fused_score"] > th_f else "LOW")
        return (
            f"primary cause: {parts[0][0]} anomaly; secondary cause: {parts[1][0]} anomaly; "
            f"tertiary cause: {parts[2][0]} anomaly; confidence: {lvl}"
        )

    anom = df[df["pred_fused"] == 1].copy()
    anom["explanation"] = anom.apply(explain_row, axis=1)

    # plots
    for col in ["timing_norm", "payload_norm", "ml_norm", "fused_score"]:
        plt.figure(figsize=(9, 5))
        plt.hist(df[df["label"] == 0][col], bins=100, density=True, alpha=0.45, label="normal")
        plt.hist(df[df["label"] == 1][col], bins=100, density=True, alpha=0.45, label="attack")
        plt.title(f"{col} distribution")
        plt.legend()
        plt.tight_layout()
        plt.savefig(plots / f"dist_{col}.png", dpi=140)
        plt.close()

    for name, score_col in [("timing", "timing_norm"), ("payload", "payload_norm"), ("ml", "ml_norm"), ("fused", "fused_score")]:
        fpr, tpr, _ = roc_curve(y, df[score_col].to_numpy(float))
        p, r, _ = precision_recall_curve(y, df[score_col].to_numpy(float))
        plt.figure(figsize=(6, 5))
        plt.plot(fpr, tpr)
        plt.plot([0, 1], [0, 1], "--", color="gray")
        plt.title(f"ROC {name}")
        plt.tight_layout()
        plt.savefig(plots / f"roc_{name}.png", dpi=140)
        plt.close()
        plt.figure(figsize=(6, 5))
        plt.plot(r, p)
        plt.title(f"PR {name}")
        plt.tight_layout()
        plt.savefig(plots / f"pr_{name}.png", dpi=140)
        plt.close()

    # save
    corr_df.to_csv(args.out / "score_correlations.csv", index=False)
    dom_df.to_csv(args.out / "attack_dominance_matrix.csv", index=False)
    per_attack_df.to_csv(args.out / "per_attack_comparison.csv", index=False)
    pd.DataFrame([fp_overlap]).to_csv(args.out / "fp_overlap_summary.csv", index=False)
    pd.DataFrame([{ "family": k, **v } for k, v in comp.items()]).to_csv(args.out / "global_comparison_metrics.csv", index=False)
    df.to_csv(args.out / "hybrid_scored_samples.csv", index=False)
    anom[["timestamp", "can_id", "attack_type", "label", "fused_score", "explanation"]].head(2000).to_csv(args.out / "explainable_anomalies.csv", index=False)
    (args.out / "fusion_config.json").write_text(json.dumps({"w_timing": wt, "w_payload": wp, "w_ml": wm, "thresholds": {"timing": th_t, "payload": th_p, "ml": th_m, "fused": th_f}}, indent=2), encoding="utf-8")

    print("Phase 8 complete: complementarity, normalization, controlled fusion, validation, explainability artifacts saved.")


if __name__ == "__main__":
    main()
