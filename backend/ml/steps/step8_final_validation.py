from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import auc, confusion_matrix, precision_recall_curve, roc_curve

PROJECT_ROOT = Path(__file__).resolve().parents[3]
EVAL_ROOT = PROJECT_ROOT / "assets" / "evaluation"
FUSION_ROOT = EVAL_ROOT / "fusion"
FINAL_ROOT = EVAL_ROOT / "final"
ATTACKS = ["DoS", "Fuzzy", "RPM", "gear"]
STATES = ["idle", "parking", "driving"]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--fusion-root", type=Path, default=FUSION_ROOT)
    p.add_argument("--out", type=Path, default=FINAL_ROOT)
    return p.parse_args()


def _metric_pack(y_true: np.ndarray, score: np.ndarray, pred: np.ndarray) -> dict[str, float]:
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
        "tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp),
    }


def main() -> None:
    args = parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    print(f"[STEP8] Loading fusion scores... | elapsed={time.perf_counter()-t0:.2f}s")

    inp = args.fusion_root / "hybrid_fusion_scores.csv"
    if not inp.exists():
        print(f"[STEP8] Missing {inp}")
        return
    df = pd.read_csv(inp, low_memory=False)
    if df.empty:
        print("[STEP8] Empty fusion scores")
        return

    for c in ["label", "fusion_prediction"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(int)
    df["fusion_score"] = pd.to_numeric(df["fusion_score"], errors="coerce").fillna(0.0)
    df["timestamp"] = pd.to_numeric(df.get("timestamp", pd.Series(dtype=float)), errors="coerce")
    if "ml_state" in df.columns:
        df["state"] = df["ml_state"].astype(str).str.lower().str.strip()
    elif "state" in df.columns:
        df["state"] = df["state"].astype(str).str.lower().str.strip()
    else:
        df["state"] = "unknown"

    print(f"[STEP8] Computing global + per-attack + per-state metrics... | elapsed={time.perf_counter()-t0:.2f}s")
    y = df["label"].to_numpy(int)
    s = df["fusion_score"].to_numpy(float)
    p = df["fusion_prediction"].to_numpy(int)
    overall = _metric_pack(y, s, p)

    per_attack = []
    for atk in ATTACKS:
        sub = df[df["attack_type"].isin(["normal", atk])]
        if sub.empty:
            continue
        per_attack.append({"attack_type": atk, **_metric_pack(sub["label"].to_numpy(int), sub["fusion_score"].to_numpy(float), sub["fusion_prediction"].to_numpy(int))})

    per_state = []
    for st in STATES:
        sub = df[df["state"] == st]
        if len(sub) < 20 or sub["label"].nunique() < 2:
            continue
        per_state.append({"state": st, **_metric_pack(sub["label"].to_numpy(int), sub["fusion_score"].to_numpy(float), sub["fusion_prediction"].to_numpy(int))})

    # detection latency per attack
    lat_rows = []
    for atk in ATTACKS:
        sub = df[df["attack_type"] == atk].sort_values("timestamp")
        if sub.empty:
            continue
        first_tp = sub[(sub["label"] == 1) & (sub["fusion_prediction"] == 1)]
        t_detect = float(first_tp["timestamp"].iloc[0]) if not first_tp.empty else float("nan")
        t_start = float(sub["timestamp"].min()) if sub["timestamp"].notna().any() else float("nan")
        lat_rows.append({"attack_type": atk, "detection_latency": t_detect - t_start if np.isfinite(t_detect) and np.isfinite(t_start) else float("nan")})

    # false-positive audit
    fps = df[(df["label"] == 0) & (df["fusion_prediction"] == 1)].copy()
    fps["dominant_contributor"] = fps.get("dominant_contributor", "fusion_timing_contrib")
    fps = fps.sort_values("fusion_score", ascending=False)
    fp_cols = [
        "timestamp", "can_id", "attack_type", "state", "fusion_score",
        "timing_norm_score", "payload_norm_score", "ml_norm_score", "sustained_dominance_score", "dominant_contributor",
    ]
    for c in fp_cols:
        if c not in fps.columns:
            fps[c] = np.nan
    fps[fp_cols].head(2000).to_csv(args.out / "false_positive_audit.csv", index=False)

    # essential plots only
    print(f"[STEP8] Rendering essential plots... | elapsed={time.perf_counter()-t0:.2f}s")
    cm = confusion_matrix(y, p, labels=[0, 1])
    fig, ax = plt.subplots(1, 1, figsize=(5, 4))
    im = ax.imshow(cm, cmap="Blues")
    for i in range(2):
        for j in range(2):
            ax.text(j, i, str(cm[i, j]), ha="center", va="center", color="black")
    ax.set_xticks([0, 1]); ax.set_xticklabels(["normal", "attack"])
    ax.set_yticks([0, 1]); ax.set_yticklabels(["normal", "attack"])
    ax.set_title("Final Confusion Matrix")
    fig.colorbar(im, ax=ax)
    fig.tight_layout()
    fig.savefig(args.out / "final_confusion_matrices.png", dpi=140)
    plt.close(fig)

    fpr, tpr, _ = roc_curve(y, s)
    plt.figure(figsize=(6, 5)); plt.plot(fpr, tpr); plt.plot([0, 1], [0, 1], "--", color="gray"); plt.title("Fusion ROC"); plt.tight_layout(); plt.savefig(args.out / "final_roc_curve.png", dpi=140); plt.close()

    plt.figure(figsize=(8, 5))
    plt.hist(df[df["label"] == 0]["fusion_score"], bins=80, density=True, alpha=0.5, label="normal")
    plt.hist(df[df["label"] == 1]["fusion_score"], bins=80, density=True, alpha=0.5, label="attack")
    plt.title("Fusion Score Distributions")
    plt.legend(); plt.tight_layout(); plt.savefig(args.out / "fusion_distributions.png", dpi=140); plt.close()

    view = df.sort_values("timestamp").head(20000)
    plt.figure(figsize=(10, 4)); plt.plot(view["timestamp"], view["fusion_score"], lw=0.8); plt.title("Detection Timeline (sample)"); plt.tight_layout(); plt.savefig(args.out / "detection_timeline.png", dpi=140); plt.close()

    fpv = view[(view["label"] == 0) & (view["fusion_prediction"] == 1)]
    plt.figure(figsize=(10, 3)); plt.scatter(fpv["timestamp"], fpv["fusion_score"], s=6, alpha=0.7); plt.title("False-Positive Timeline Inspection (sample)"); plt.tight_layout(); plt.savefig(args.out / "false_positive_timeline.png", dpi=140); plt.close()

    # summary jsons
    per_attack_df = pd.DataFrame(per_attack)
    per_state_df = pd.DataFrame(per_state)
    latency_df = pd.DataFrame(lat_rows)
    strongest = "n/a"
    weakest = "n/a"
    if {"fusion_timing_contrib", "fusion_payload_contrib", "fusion_ml_contrib", "fusion_temporal_contrib"}.issubset(df.columns):
        means = df[["fusion_timing_contrib", "fusion_payload_contrib", "fusion_ml_contrib", "fusion_temporal_contrib"]].mean().sort_values(ascending=False)
        strongest, weakest = str(means.index[0]), str(means.index[-1])

    hardest = "n/a"
    if not per_attack_df.empty:
        hardest = str(per_attack_df.sort_values("recall", ascending=True).iloc[0]["attack_type"])

    threshold_summary = {}
    th_path = args.fusion_root / "threshold_summary.json"
    if th_path.exists():
        threshold_summary = json.loads(th_path.read_text(encoding="utf-8"))

    final_metrics = {
        "overall": overall,
        "per_attack": per_attack,
        "per_state": per_state,
        "detection_latency": lat_rows,
        "best_threshold": threshold_summary.get("selected_threshold"),
        "hardest_attack_type": hardest,
        "strongest_detection_layer": strongest,
        "weakest_detection_layer": weakest,
    }

    (args.out / "final_metrics.json").write_text(json.dumps(final_metrics, indent=2), encoding="utf-8")
    (args.out / "threshold_summary.json").write_text(json.dumps(threshold_summary, indent=2), encoding="utf-8")
    per_attack_df.to_csv(args.out / "per_attack_metrics.csv", index=False)
    per_state_df.to_csv(args.out / "per_state_metrics.csv", index=False)
    latency_df.to_csv(args.out / "detection_latency.csv", index=False)

    print("FINAL SYSTEM SUMMARY:")
    print(f"- overall recall: {overall['recall']:.4f}")
    print(f"- overall precision: {overall['precision']:.4f}")
    print(f"- F1: {overall['f1']:.4f}")
    print(f"- false positive rate: {overall['fpr']:.4f}")
    print(f"- best threshold: {threshold_summary.get('selected_threshold')}")
    print(f"- hardest attack type: {hardest}")
    print(f"- strongest detection layer: {strongest}")
    print(f"- weakest detection layer: {weakest}")
    print(f"[STEP8] Done | elapsed={time.perf_counter()-t0:.2f}s")


if __name__ == "__main__":
    main()
