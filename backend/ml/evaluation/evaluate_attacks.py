from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
from sklearn.metrics import auc, confusion_matrix, f1_score, precision_recall_curve, precision_score, recall_score, roc_auc_score, roc_curve

try:
    from backend.ml.feature_engineering import preprocess_pipeline, FEATURE_COLS
    from backend.ml.state_based_pipeline import infer
    from backend.ml.can_data_cleaning import clean_can_dataframe, CleaningConfig
except ModuleNotFoundError:
    sys.path.append(str(Path(__file__).resolve().parents[3]))
    from backend.ml.feature_engineering import preprocess_pipeline, FEATURE_COLS
    from backend.ml.state_based_pipeline import infer
    from backend.ml.can_data_cleaning import clean_can_dataframe, CleaningConfig

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ARCHIVE_ROOT = PROJECT_ROOT / "assets" / "archive"
EVAL_ROOT = PROJECT_ROOT / "assets" / "evaluation"
PROCESSED_DATASET = PROJECT_ROOT / "backend" / "ml" / "processed_dataset.csv"
ATTACK_FILES = {"DoS": "DoS_dataset.csv", "Fuzzy": "Fuzzy_dataset.csv", "RPM": "RPM_dataset.csv", "gear": "gear_dataset.csv"}
STATE_NAMES = ["idle", "parking", "driving"]
MAX_ROWS_PER_STATE = 50000
logger = logging.getLogger("eval_attacks")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--processed", type=Path, default=PROCESSED_DATASET)
    p.add_argument("--archive", type=Path, default=ARCHIVE_ROOT)
    p.add_argument("--out", type=Path, default=EVAL_ROOT)
    p.add_argument("--fast", action="store_true")
    return p.parse_args()


def _ensure_raw_attack_shape(df: pd.DataFrame) -> pd.DataFrame:
    def _safe_hex_to_int(v: object) -> float:
        if pd.isna(v):
            return np.nan
        s = str(v).strip()
        if s == "" or s.lower() in {"nan", "none"}:
            return np.nan
        try:
            return float(int(s, 16))
        except Exception:
            return np.nan

    raw = df.copy(); raw.columns = [f"c{i}" for i in range(raw.shape[1])]
    out = pd.DataFrame()
    out["timestamp"] = pd.to_numeric(raw["c0"], errors="coerce")
    out["can_id"] = raw["c1"].apply(_safe_hex_to_int)
    dlc = pd.to_numeric(raw["c2"], errors="coerce")
    for i in range(8):
        out[f"b{i}"] = raw[f"c{i+3}"].apply(_safe_hex_to_int)
    out = out[dlc == 8].dropna().reset_index(drop=True)
    return out


def _metric(y_true: np.ndarray, y_pred: np.ndarray, y_score: np.ndarray) -> dict:
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    p, r, _ = precision_recall_curve(y_true, y_score)
    return {
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "roc_auc": float(roc_auc_score(y_true, y_score)),
        "pr_auc": float(auc(r, p)),
        "fpr": float(fp / (fp + tn + 1e-12)),
        "tpr": float(tp / (tp + fn + 1e-12)),
        "tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp),
    }


def _plot_confusion(y_true: np.ndarray, y_pred: np.ndarray, out: Path) -> None:
    cm = confusion_matrix(y_true, y_pred, labels=[0, 1]); cmn = cm / (cm.sum(axis=1, keepdims=True) + 1e-12)
    fig, ax = plt.subplots(1, 2, figsize=(10, 4))
    ax[0].imshow(cm, cmap="Blues"); ax[0].set_title("Counts")
    ax[1].imshow(cmn, cmap="Blues"); ax[1].set_title("Normalized")
    for a, m in [(ax[0], cm), (ax[1], cmn)]:
        for i in range(2):
            for j in range(2):
                a.text(j, i, f"{m[i,j]:.2f}" if a is ax[1] else str(int(m[i,j])), ha="center", va="center")
        a.set_xticks([0, 1]); a.set_xticklabels(["normal", "attack"]); a.set_yticks([0, 1]); a.set_yticklabels(["normal", "attack"])
    fig.tight_layout(); fig.savefig(out, dpi=140); plt.close(fig)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s][EVAL] %(message)s")
    args = parse_args()
    plots = args.out / "plots"
    roc_dir, pr_dir, score_dir = args.out / "roc_curves", args.out / "pr_curves", args.out / "score_distributions"
    sens_dir = args.out / "threshold_sensitivity"
    for d in [args.out, plots, roc_dir, pr_dir, score_dir, sens_dir]:
        d.mkdir(parents=True, exist_ok=True)

    normal_df = pd.read_csv(args.processed, low_memory=False)
    normal_scored = infer(normal_df.copy(), "kaggle_normal")
    normal_scored["label"] = 0; normal_scored["attack_type"] = "normal"

    overall, per_state_rows, per_attack_rows, pred_rows, best_th_rows = {}, [], [], [], []

    for attack, fname in ATTACK_FILES.items():
        path = args.archive / fname
        if not path.exists():
            continue
        raw = pd.read_csv(path, header=None, low_memory=False)
        raw = _ensure_raw_attack_shape(raw)
        raw = clean_can_dataframe(raw, PROJECT_ROOT / "backend" / "ml" / "cleaning" / f"eval_{attack.lower()}", f"eval_{attack.lower()}", CleaningConfig(min_can_occurrence=2, max_dt_quantile=0.9995), False)
        feat, _, _ = preprocess_pipeline(raw, scaler=None, fit=True)
        atk = infer(feat.copy(), attack.lower())
        atk["label"] = 1; atk["attack_type"] = attack

        for st in STATE_NAMES:
            n = normal_scored[normal_scored["state"].astype(str).str.lower() == st]
            a = atk[atk["state"].astype(str).str.lower() == st]
            if n.empty or a.empty:
                continue
            if args.fast:
                n = n.sample(min(len(n), MAX_ROWS_PER_STATE), random_state=42)
                a = a.sample(min(len(a), MAX_ROWS_PER_STATE), random_state=42)
            c = pd.concat([n, a], ignore_index=True).dropna(subset=["smoothed_score", "is_anomaly"])            
            y_true = c["label"].to_numpy(int)
            y_score = (-c["smoothed_score"]).to_numpy(float)

            # per-state threshold optimization
            th_grid = np.quantile(c["smoothed_score"].to_numpy(float), np.linspace(0.05, 0.95, 40))
            best = (None, -1.0, 0.0, 0.0)
            for th in th_grid:
                yp = (c["smoothed_score"].to_numpy(float) < th).astype(int)
                p = precision_score(y_true, yp, zero_division=0); r = recall_score(y_true, yp, zero_division=0); f1 = f1_score(y_true, yp, zero_division=0)
                if f1 > best[1]:
                    best = (float(th), float(f1), float(p), float(r))
            best_th_rows.append({"attack": attack, "state": st, "threshold": best[0], "precision": best[2], "recall": best[3], "f1": best[1]})
            y_pred = (c["smoothed_score"].to_numpy(float) < best[0]).astype(int)
            m = _metric(y_true, y_pred, y_score)
            per_state_rows.append({"attack": attack, "state": st, **m})

            # threshold sweep
            sweep = []
            for th in th_grid:
                yp = (c["smoothed_score"].to_numpy(float) < th).astype(int)
                sweep.append((th, precision_score(y_true, yp, zero_division=0), recall_score(y_true, yp, zero_division=0), f1_score(y_true, yp, zero_division=0)))
            s = np.array(sweep)
            plt.figure(figsize=(8, 5)); plt.plot(s[:,0], s[:,1], label="precision"); plt.plot(s[:,0], s[:,2], label="recall"); plt.plot(s[:,0], s[:,3], label="f1"); plt.title(f"Threshold Sweep - {attack} - {st}"); plt.xlabel("threshold"); plt.ylabel("metric"); plt.legend(); plt.tight_layout(); plt.savefig(sens_dir / f"threshold_sensitivity_{attack}_{st}.png", dpi=140); plt.close()

            # PCA plot
            fn = [f for f in FEATURE_COLS if f in c.columns]
            x_n = n[fn].to_numpy(float); x_a = a[fn].to_numpy(float)
            comb = np.vstack([x_n, x_a]); z = PCA(n_components=2).fit_transform(comb)
            zn, za = z[:len(x_n)], z[len(x_n):]
            plt.figure(figsize=(8,6)); plt.scatter(zn[:,0], zn[:,1], s=6, alpha=0.35, c="blue", label="normal"); plt.scatter(za[:,0], za[:,1], s=6, alpha=0.55, c="red", label=attack); plt.xlabel("PCA1"); plt.ylabel("PCA2"); plt.title(f"{attack} - {st}"); plt.legend(); plt.tight_layout(); plt.savefig(plots / f"pca_{attack}_{st}.png", dpi=140); plt.close()

        combined = pd.concat([normal_scored, atk], ignore_index=True).dropna(subset=["smoothed_score", "is_anomaly"])
        y_true = combined["label"].to_numpy(int); y_score = (-combined["smoothed_score"]).to_numpy(float); y_pred = combined["is_anomaly"].to_numpy(int)
        m = _metric(y_true, y_pred, y_score)
        overall[attack] = m; per_attack_rows.append({"attack_type": attack, "precision": m["precision"], "recall": m["recall"], "F1": m["f1"], "support": int(len(combined))})

        fpr, tpr, _ = roc_curve(y_true, y_score); plt.figure(figsize=(7,6)); plt.plot(fpr,tpr,label=f"AUC={m['roc_auc']:.3f}"); plt.plot([0,1],[0,1],'--',c='gray'); plt.title(f"ROC - {attack}"); plt.xlabel("FPR"); plt.ylabel("TPR"); plt.legend(); plt.tight_layout(); plt.savefig(roc_dir / f"roc_{attack}.png", dpi=140); plt.close()
        p, r, _ = precision_recall_curve(y_true, y_score); plt.figure(figsize=(7,6)); plt.plot(r,p,label=f"PR-AUC={m['pr_auc']:.3f}"); plt.title(f"PR - {attack}"); plt.xlabel("Recall"); plt.ylabel("Precision"); plt.legend(); plt.tight_layout(); plt.savefig(pr_dir / f"pr_{attack}.png", dpi=140); plt.close()
        ns = normal_scored["smoothed_score"].dropna().to_numpy(float); aas = atk["smoothed_score"].dropna().to_numpy(float)
        plt.figure(figsize=(9,5)); plt.hist(ns,bins=60,alpha=0.5,density=True,label="normal"); plt.hist(aas,bins=60,alpha=0.5,density=True,label=attack); plt.axvline(np.median(ns),ls='--',c='black'); plt.axvline(np.median(aas),ls='--',c='red'); plt.title(f"Score Distribution: normal vs {attack}"); plt.xlabel("smoothed_score"); plt.ylabel("density"); plt.legend(); plt.tight_layout(); plt.savefig(score_dir / f"scores_normal_vs_{attack}.png", dpi=140); plt.close()
        _plot_confusion(y_true, y_pred, plots / f"confusion_{attack}.png")

        pred_rows.append(combined[["timestamp", "state", "attack_type", "label", "smoothed_score", "is_anomaly"]].rename(columns={"smoothed_score": "score", "is_anomaly": "prediction"}))

    pd.concat(pred_rows, ignore_index=True).to_csv(args.out / "predictions.csv", index=False)
    pd.DataFrame(per_state_rows).to_csv(args.out / "metrics_summary.csv", index=False)
    pd.DataFrame(per_attack_rows).to_csv(args.out / "per_attack_metrics.csv", index=False)
    pd.DataFrame(best_th_rows).to_csv(args.out / "best_thresholds.csv", index=False)
    (args.out / "overall_metrics.json").write_text(json.dumps(overall, indent=2), encoding="utf-8")
    (args.out / "per_state_metrics.json").write_text(pd.DataFrame(per_state_rows).to_json(orient="records", indent=2), encoding="utf-8")
    (args.out / "per_attack_metrics.json").write_text(pd.DataFrame(per_attack_rows).to_json(orient="records", indent=2), encoding="utf-8")

    om = pd.DataFrame([{"attack":k, **v} for k,v in overall.items()])
    best_attack = om.sort_values("f1", ascending=False).iloc[0]["attack"] if not om.empty else "n/a"
    worst_attack = om.sort_values("f1", ascending=True).iloc[0]["attack"] if not om.empty else "n/a"
    sm = pd.DataFrame(per_state_rows)
    state_mean = sm.groupby("state")["f1"].mean().sort_values() if not sm.empty else pd.Series(dtype=float)
    best_state = state_mean.index[-1] if len(state_mean) else "n/a"
    worst_state = state_mean.index[0] if len(state_mean) else "n/a"
    fp = int(om["fp"].sum()) if not om.empty else 0; fn = int(om["fn"].sum()) if not om.empty else 0

    overall_txt = om.to_string(index=False) if not om.empty else "none"
    per_state_txt = sm.to_string(index=False) if not sm.empty else "none"
    th_txt = pd.DataFrame(best_th_rows).to_string(index=False) if best_th_rows else "none"

    final = [
        "# Final CAN IDS Evaluation Report", "",
        "## Overall metrics per attack", overall_txt, "",
        "## Per-state metrics", per_state_txt, "",
        f"- Best attack: {best_attack}", f"- Worst attack: {worst_attack}", f"- Best state: {best_state}", f"- Worst state: {worst_state}",
        f"- Total false positives: {fp}", f"- Total false negatives: {fn}",
        "",
        "## Metric meanings",
        "- Precision: when IDS alerts, how often it is correct.",
        "- Recall: how many real attacks IDS catches.",
        "- F1: balance between precision and recall.",
        "- ROC-AUC: ranking quality across thresholds.",
        "- PR-AUC: alert quality under class imbalance.",
        "",
        "## Threshold optimization", th_txt,
    ]
    (args.out / "final_report.md").write_text("\n".join(final), encoding="utf-8")
    (args.out / "evaluation_report.txt").write_text("\n".join(final), encoding="utf-8")

    print("Precision answers: when the IDS raises an alert, how often is it correct?")
    print("Recall answers: how many true attacks are detected?")
    print("F1 balances precision and recall in one score.")
    print("ROC-AUC measures how well normal/attack are ranked.")
    print("PR-AUC measures precision-recall tradeoff under imbalance.")


if __name__ == "__main__":
    main()
