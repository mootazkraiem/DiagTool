from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)


STATES = ["driving", "idle", "parking"]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Full inference-only evaluation for CAN anomaly detection.")
    p.add_argument("--dataset", type=Path, required=True)
    p.add_argument("--models-dir", type=Path, default=Path("assets/models"))
    p.add_argument("--output-dir", type=Path, default=Path("evaluation_results"))
    p.add_argument("--plots", action="store_true")
    p.add_argument("--per-state", action="store_true")
    p.add_argument("--per-attack", action="store_true")
    p.add_argument("--roc", action="store_true")
    p.add_argument("--pr", action="store_true")
    p.add_argument("--confusion", action="store_true")
    p.add_argument("--threshold-sweep", action="store_true")
    p.add_argument("--save-predictions", action="store_true")
    return p.parse_args()


def ensure_paths(args: argparse.Namespace) -> dict[str, Path]:
    if not args.dataset.exists():
        raise FileNotFoundError(f"Dataset not found: {args.dataset}")
    for req in ["state_scaler.joblib", "kmeans_state_model.joblib", "state_mapping.json"]:
        if not (args.models_dir / req).exists():
            raise FileNotFoundError(f"Missing model artifact: {args.models_dir / req}")

    out = args.output_dir
    plots = out / "plots"
    paths = {
        "root": out,
        "plots": plots,
    }
    out.mkdir(parents=True, exist_ok=True)
    plots.mkdir(parents=True, exist_ok=True)
    return paths


def compute_metrics(y_true: np.ndarray, y_pred: np.ndarray, score: np.ndarray) -> Dict[str, float]:
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "roc_auc": float(roc_auc_score(y_true, score)) if len(np.unique(y_true)) > 1 else float("nan"),
        "pr_auc": float(average_precision_score(y_true, score)) if len(np.unique(y_true)) > 1 else float("nan"),
        "tn": int(tn),
        "fp": int(fp),
        "fn": int(fn),
        "tp": int(tp),
        "false_positive_rate": float(fp / (fp + tn + 1e-12)),
        "true_positive_rate": float(tp / (tp + fn + 1e-12)),
    }


def plot_roc(y_true: np.ndarray, score: np.ndarray, title: str, out: Path) -> None:
    fpr, tpr, _ = roc_curve(y_true, score)
    aucv = roc_auc_score(y_true, score)
    plt.figure(figsize=(7, 6))
    plt.plot(fpr, tpr, label=f"AUC={aucv:.3f}")
    plt.plot([0, 1], [0, 1], "--", color="gray")
    plt.title(title)
    plt.xlabel("False Positive Rate")
    plt.ylabel("True Positive Rate")
    plt.legend()
    plt.tight_layout()
    plt.savefig(out, dpi=140)
    plt.close()


def plot_pr(y_true: np.ndarray, score: np.ndarray, title: str, out: Path) -> None:
    p, r, _ = precision_recall_curve(y_true, score)
    ap = average_precision_score(y_true, score)
    plt.figure(figsize=(7, 6))
    plt.plot(r, p, label=f"PR-AUC={ap:.3f}")
    plt.title(title)
    plt.xlabel("Recall")
    plt.ylabel("Precision")
    plt.legend()
    plt.tight_layout()
    plt.savefig(out, dpi=140)
    plt.close()


def plot_conf(y_true: np.ndarray, y_pred: np.ndarray, title: str, out: Path) -> None:
    cm = confusion_matrix(y_true, y_pred, labels=[0, 1])
    plt.figure(figsize=(6, 5))
    plt.imshow(cm, cmap="Blues")
    for i in range(cm.shape[0]):
        for j in range(cm.shape[1]):
            plt.text(j, i, str(cm[i, j]), ha="center", va="center")
    plt.xticks([0, 1], ["normal", "anomaly"])
    plt.yticks([0, 1], ["normal", "anomaly"])
    plt.colorbar()
    plt.title(title)
    plt.xlabel("Predicted")
    plt.ylabel("True")
    plt.tight_layout()
    plt.savefig(out, dpi=140)
    plt.close()


def plot_scores(df: pd.DataFrame, state: str, out: Path) -> None:
    s = df[df["state"] == state]
    if s.empty:
        return
    normal = s[s["label"] == 0]["score"].dropna().to_numpy()
    anom = s[s["label"] == 1]["score"].dropna().to_numpy()
    th = np.quantile(normal, 0.95) if len(normal) else 0.5
    plt.figure(figsize=(8, 5))
    plt.hist(normal, bins=40, alpha=0.6, density=True, label="normal")
    plt.hist(anom, bins=40, alpha=0.6, density=True, label="anomaly")
    if len(normal) > 1:
        h, e = np.histogram(normal, bins=100, density=True)
        c = 0.5 * (e[:-1] + e[1:])
        plt.plot(c, h, label="normal KDE-like")
    if len(anom) > 1:
        h, e = np.histogram(anom, bins=100, density=True)
        c = 0.5 * (e[:-1] + e[1:])
        plt.plot(c, h, label="anomaly KDE-like")
    plt.axvline(th, linestyle="--", color="red", label="threshold")
    plt.title(f"Score Distribution - {state}")
    plt.xlabel("score")
    plt.ylabel("density")
    plt.legend()
    plt.tight_layout()
    plt.savefig(out, dpi=140)
    plt.close()


def plot_threshold_sweep(df: pd.DataFrame, state: str, out: Path) -> None:
    s = df[df["state"] == state].dropna(subset=["score"])
    if s.empty:
        return
    y = s["label"].to_numpy(dtype=int)
    score = s["score"].to_numpy(dtype=float)
    ths = np.quantile(score, np.linspace(0.05, 0.95, 30))
    rows = []
    for th in ths:
        pred = (score >= th).astype(int)
        rows.append((th, precision_score(y, pred, zero_division=0), recall_score(y, pred, zero_division=0), f1_score(y, pred, zero_division=0)))
    arr = np.asarray(rows)
    plt.figure(figsize=(8, 5))
    plt.plot(arr[:, 0], arr[:, 1], label="precision")
    plt.plot(arr[:, 0], arr[:, 2], label="recall")
    plt.plot(arr[:, 0], arr[:, 3], label="f1")
    plt.title(f"Threshold Sweep - {state}")
    plt.xlabel("threshold")
    plt.ylabel("metric")
    plt.legend()
    plt.tight_layout()
    plt.savefig(out, dpi=140)
    plt.close()


def main() -> None:
    args = parse_args()
    paths = ensure_paths(args)

    df = pd.read_csv(args.dataset, low_memory=False)
    required = ["timestamp", "state", "attack_type", "label"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    if "smoothed_score" in df.columns:
        df["score"] = -pd.to_numeric(df["smoothed_score"], errors="coerce")
    elif "anomaly_score" in df.columns:
        df["score"] = -pd.to_numeric(df["anomaly_score"], errors="coerce")
    elif "score" in df.columns:
        df["score"] = pd.to_numeric(df["score"], errors="coerce")
    else:
        raise ValueError("Dataset needs one of: smoothed_score, anomaly_score, or score")

    df["label"] = pd.to_numeric(df["label"], errors="coerce").fillna(0).astype(int)
    df["state"] = df["state"].astype(str).str.lower().str.strip()
    df["attack_type"] = df["attack_type"].fillna("unknown").astype(str)
    df = df.dropna(subset=["score"]).copy()

    global_threshold = float(np.quantile(df[df["label"] == 0]["score"], 0.95)) if (df["label"] == 0).any() else 0.5
    df["prediction"] = (df["score"] >= global_threshold).astype(int)

    # basic integrity checks
    if not set(df["label"].unique()).issubset({0, 1}):
        raise ValueError("label integrity failed: expected only 0/1")

    metrics_rows: List[Dict[str, object]] = []

    # global
    gm = compute_metrics(df["label"].to_numpy(), df["prediction"].to_numpy(), df["score"].to_numpy())
    metrics_rows.append({"scope": "global", "name": "global", **gm})

    if args.plots and args.roc:
        plot_roc(df["label"].to_numpy(), df["score"].to_numpy(), "ROC - Global", paths["plots"] / "roc_global.png")
    if args.plots and args.pr:
        plot_pr(df["label"].to_numpy(), df["score"].to_numpy(), "PR - Global", paths["plots"] / "pr_global.png")
    if args.plots and args.confusion:
        plot_conf(df["label"].to_numpy(), df["prediction"].to_numpy(), "Confusion - Global", paths["plots"] / "confusion_global.png")

    # per-state
    if args.per_state:
        for st in STATES:
            s = df[df["state"] == st].copy()
            if s.empty:
                continue
            th = float(np.quantile(s[s["label"] == 0]["score"], 0.95)) if (s["label"] == 0).any() else global_threshold
            s["prediction"] = (s["score"] >= th).astype(int)
            m = compute_metrics(s["label"].to_numpy(), s["prediction"].to_numpy(), s["score"].to_numpy())
            metrics_rows.append({"scope": "state", "name": st, **m})
            if args.plots and args.roc:
                plot_roc(s["label"].to_numpy(), s["score"].to_numpy(), f"ROC - {st}", paths["plots"] / f"roc_{st}.png")
            if args.plots and args.pr:
                plot_pr(s["label"].to_numpy(), s["score"].to_numpy(), f"PR - {st}", paths["plots"] / f"pr_{st}.png")
            if args.plots and args.confusion:
                plot_conf(s["label"].to_numpy(), s["prediction"].to_numpy(), f"Confusion - {st}", paths["plots"] / f"confusion_{st}.png")
            if args.plots:
                plot_scores(s, st, paths["plots"] / f"score_distribution_{st}.png")
            if args.plots and args.threshold_sweep:
                plot_threshold_sweep(s, st, paths["plots"] / f"threshold_sweep_{st}.png")

    # per-attack
    attack_rows = []
    if args.per_attack:
        for atk, g in df.groupby("attack_type", sort=False):
            if len(g) < 5:
                continue
            pred = g["prediction"].to_numpy()
            y = g["label"].to_numpy()
            attack_rows.append({
                "attack_type": atk,
                "precision": float(precision_score(y, pred, zero_division=0)),
                "recall": float(recall_score(y, pred, zero_division=0)),
                "F1": float(f1_score(y, pred, zero_division=0)),
                "support": int(len(g)),
            })

    pd.DataFrame(metrics_rows).to_csv(paths["root"] / "metrics_summary.csv", index=False)
    pd.DataFrame(attack_rows).to_csv(paths["root"] / "per_attack_metrics.csv", index=False)
    if args.save_predictions:
        df[["timestamp", "state", "attack_type", "label", "score", "prediction"]].to_csv(paths["root"] / "predictions.csv", index=False)

    # fp/fn analysis
    fp = df[(df["label"] == 0) & (df["prediction"] == 1)]
    fn = df[(df["label"] == 1) & (df["prediction"] == 0)]
    fp_state = fp["state"].value_counts().to_dict()
    fn_state = fn["state"].value_counts().to_dict()
    fp_attack = fp["attack_type"].value_counts().head(5).to_dict()
    fn_attack = fn["attack_type"].value_counts().head(5).to_dict()

    state_metrics = [r for r in metrics_rows if r["scope"] == "state"]
    best_state = max(state_metrics, key=lambda x: x["f1"])["name"] if state_metrics else "n/a"
    worst_state = min(state_metrics, key=lambda x: x["f1"])["name"] if state_metrics else "n/a"

    attack_df = pd.DataFrame(attack_rows)
    easiest_attack = attack_df.sort_values("F1", ascending=False).iloc[0]["attack_type"] if not attack_df.empty else "n/a"
    hardest_attack = attack_df.sort_values("F1", ascending=True).iloc[0]["attack_type"] if not attack_df.empty else "n/a"

    print(f"best performing state: {best_state}")
    print(f"worst performing state: {worst_state}")
    print(f"hardest attack type: {hardest_attack}")
    print(f"easiest attack type: {easiest_attack}")
    print(f"overall ROC-AUC: {gm['roc_auc']:.4f}")
    print(f"overall PR-AUC: {gm['pr_auc']:.4f}")
    print(f"total false positives: {len(fp)}")
    print(f"total false negatives: {len(fn)}")
    print(f"FP count per state: {json.dumps(fp_state)}")
    print(f"FP top attack types: {json.dumps(fp_attack)}")
    print(f"FN count per state: {json.dumps(fn_state)}")
    print(f"missed attack types: {json.dumps(fn_attack)}")


if __name__ == "__main__":
    main()
