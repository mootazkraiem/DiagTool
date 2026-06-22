from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.stats import ks_2samp
from sklearn.decomposition import PCA
from sklearn.ensemble import RandomForestClassifier
from sklearn.manifold import TSNE
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler

try:
    from xgboost import XGBClassifier
    XGB_AVAILABLE = True
except Exception:
    XGB_AVAILABLE = False

PROJECT_ROOT = Path(__file__).resolve().parents[2]
AUDIT_DIR = PROJECT_ROOT / "backend" / "ml" / "audit"
PLOTS_DIR = AUDIT_DIR / "plots"
BYTE_COLS = [f"b{i}" for i in range(8)]
META_COLS = {"timestamp", "can_id", "state", "vehicle", "label"}

logger = logging.getLogger("dataset_audit")


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="CAN anomaly dataset audit")
    p.add_argument("--dataset", type=str, required=True, help="Path to processed labeled CSV/Parquet dataset")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--sample-size", type=int, default=100)
    return p.parse_args()


def load_dataset(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Dataset not found: {path}")
    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path)
    elif path.suffix.lower() in {".parquet", ".pq"}:
        df = pd.read_parquet(path)
    else:
        raise ValueError("Unsupported format; use CSV or Parquet")

    if "label" not in df.columns:
        raise ValueError("Missing required label column (0=normal,1=anomaly)")
    if not set(pd.unique(df["label"].dropna())).issuperset({0, 1}):
        raise ValueError("Dataset must include both label classes 0 and 1")
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce")
    return df.replace([np.inf, -np.inf], np.nan)


def get_numeric_features(df: pd.DataFrame) -> List[str]:
    numeric = [c for c in df.columns if c not in META_COLS and pd.api.types.is_numeric_dtype(df[c])]
    return [c for c in numeric if df[c].notna().sum() > 5]


def sample_classes(df: pd.DataFrame, n: int, seed: int) -> Tuple[pd.DataFrame, pd.DataFrame]:
    normal = df[df["label"] == 0]
    anomaly = df[df["label"] == 1]
    if len(normal) < n or len(anomaly) < n:
        raise ValueError(f"Need at least {n} rows per class; got normal={len(normal)}, anomaly={len(anomaly)}")
    return normal.sample(n=n, random_state=seed), anomaly.sample(n=n, random_state=seed)


def describe_stats(n_df: pd.DataFrame, a_df: pd.DataFrame, features: List[str]) -> Tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    for f in features:
        nv = n_df[f].dropna().to_numpy()
        av = a_df[f].dropna().to_numpy()
        if len(nv) < 3 or len(av) < 3:
            continue
        n_mu, a_mu = np.mean(nv), np.mean(av)
        n_sd, a_sd = np.std(nv, ddof=1), np.std(av, ddof=1)
        pooled = np.sqrt((n_sd**2 + a_sd**2) / 2.0) + 1e-12
        d = abs(a_mu - n_mu) / pooled
        ks, _ = ks_2samp(nv, av)
        n_min, n_max = np.min(nv), np.max(nv)
        a_min, a_max = np.min(av), np.max(av)
        overlap = max(0.0, min(n_max, a_max) - max(n_min, a_min)) / (max(n_max, a_max) - min(n_min, a_min) + 1e-12)
        rows.append({
            "feature": f,
            "normal_mean": n_mu,
            "normal_std": n_sd,
            "normal_median": np.median(nv),
            "normal_min": n_min,
            "normal_max": n_max,
            "anomaly_mean": a_mu,
            "anomaly_std": a_sd,
            "anomaly_median": np.median(av),
            "anomaly_min": a_min,
            "anomaly_max": a_max,
            "cohens_d": d,
            "ks_stat": ks,
            "overlap_estimate": overlap,
            "separability_score": (d + ks + (1.0 - overlap)) / 3.0,
        })
    stats = pd.DataFrame(rows).sort_values("separability_score", ascending=False)
    return stats, stats[["feature", "separability_score", "cohens_d", "ks_stat", "overlap_estimate"]]


def nearest_neighbor_purity(df: pd.DataFrame, features: List[str]) -> Dict[str, float]:
    x = df[features].fillna(0.0).to_numpy(dtype=np.float32)
    y = df["label"].to_numpy()
    x = StandardScaler().fit_transform(x)
    nn = NearestNeighbors(n_neighbors=6).fit(x)
    idxs = nn.kneighbors(x, return_distance=False)[:, 1:]
    purity = []
    for i in range(len(df)):
        neighbors = y[idxs[i]]
        same = np.mean(neighbors == y[i])
        purity.append(same)
    purity = np.asarray(purity)
    return {
        "anomaly_neighbor_purity": float(np.mean(purity[y == 1])) if np.any(y == 1) else 0.0,
        "normal_neighbor_purity": float(np.mean(purity[y == 0])) if np.any(y == 0) else 0.0,
    }


def supervised_test(df: pd.DataFrame, features: List[str], seed: int) -> Dict[str, Dict[str, float]]:
    x = df[features].fillna(0.0)
    y = df["label"].astype(int)
    x_train, x_test, y_train, y_test = train_test_split(x, y, test_size=0.2, random_state=seed, stratify=y)

    def metric_pack(model_name: str, model) -> Dict[str, float]:
        model.fit(x_train, y_train)
        pred = model.predict(x_test)
        if hasattr(model, "predict_proba"):
            proba = model.predict_proba(x_test)[:, 1]
        else:
            proba = pred
        return {
            "accuracy": float(accuracy_score(y_test, pred)),
            "f1": float(f1_score(y_test, pred, zero_division=0)),
            "precision": float(precision_score(y_test, pred, zero_division=0)),
            "recall": float(recall_score(y_test, pred, zero_division=0)),
            "roc_auc": float(roc_auc_score(y_test, proba)),
        }

    out = {"random_forest": metric_pack("rf", RandomForestClassifier(n_estimators=300, random_state=seed, n_jobs=-1))}
    if XGB_AVAILABLE:
        out["xgboost"] = metric_pack("xgb", XGBClassifier(n_estimators=300, max_depth=6, learning_rate=0.05, subsample=0.9, colsample_bytree=0.9, random_state=seed, eval_metric="logloss"))
    return out


def temporal_analysis(df: pd.DataFrame) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for label, name in [(0, "normal"), (1, "anomaly")]:
        sub = df[df["label"] == label].copy()
        if "timestamp" in sub.columns:
            sub = sub.sort_values("timestamp")
            dt = sub["timestamp"].diff().dropna()
            out[f"{name}_timestamp_variance"] = float(np.var(dt)) if len(dt) else 0.0
            out[f"{name}_periodicity_cv"] = float(np.std(dt) / (np.mean(dt) + 1e-12)) if len(dt) else 0.0
            out[f"{name}_frozen_frame_rate"] = float(np.mean(dt == 0)) if len(dt) else 0.0
        if "can_id" in sub.columns:
            freq = sub["can_id"].value_counts(normalize=True)
            out[f"{name}_can_id_entropy"] = float(-(freq * np.log(freq + 1e-12)).sum()) if len(freq) else 0.0
            out[f"{name}_top_can_share"] = float(freq.iloc[0]) if len(freq) else 0.0
            out[f"{name}_can_id_count"] = float(sub["can_id"].nunique())
        payload_cols = [c for c in BYTE_COLS if c in sub.columns]
        if payload_cols:
            payload = sub[payload_cols].astype(str).agg("-".join, axis=1)
            out[f"{name}_repeated_payload_rate"] = float(payload.duplicated().mean())
            out[f"{name}_payload_cardinality"] = float(payload.nunique())
        if {"timestamp", "can_id"}.issubset(sub.columns):
            # Per-CAN periodicity variation reveals timing jitter/replay-like flattening.
            dt_by_id = sub.sort_values("timestamp").groupby("can_id")["timestamp"].diff()
            dt_by_id = pd.to_numeric(dt_by_id, errors="coerce").dropna()
            out[f"{name}_per_can_dt_std"] = float(dt_by_id.std()) if len(dt_by_id) else 0.0
    return out


def byte_analysis(df: pd.DataFrame) -> Dict[str, float]:
    cols = [c for c in BYTE_COLS if c in df.columns]
    if not cols:
        return {"byte_analysis": -1.0}
    out: Dict[str, float] = {}
    for label, name in [(0, "normal"), (1, "anomaly")]:
        sub = df[df["label"] == label][cols].dropna().astype(int)
        if sub.empty:
            continue
        vals = sub.to_numpy()
        row_entropy = []
        for r in vals:
            p = np.bincount(r, minlength=256).astype(float)
            p /= p.sum()
            row_entropy.append(float(-(p[p > 0] * np.log2(p[p > 0])).sum()))
        out[f"{name}_byte_entropy_mean"] = float(np.mean(row_entropy))
        out[f"{name}_changed_byte_frequency"] = float(np.mean(np.sum(np.diff(vals, axis=0) != 0, axis=1) / vals.shape[1])) if len(vals) > 1 else 0.0
    return out


def make_plots(df: pd.DataFrame, stats: pd.DataFrame, features: List[str], seed: int) -> None:
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)
    x = df[features].fillna(0.0).to_numpy(dtype=np.float32)
    y = df["label"].to_numpy()
    xs = StandardScaler().fit_transform(x)

    pca = PCA(n_components=2, random_state=seed).fit_transform(xs)
    plt.figure(figsize=(8, 6))
    plt.scatter(pca[y == 0, 0], pca[y == 0, 1], s=18, alpha=0.6, label="normal")
    plt.scatter(pca[y == 1, 0], pca[y == 1, 1], s=18, alpha=0.8, label="anomaly")
    plt.title("PCA: normal vs anomaly")
    plt.legend()
    plt.tight_layout()
    plt.savefig(PLOTS_DIR / "pca_plot.png", dpi=140)
    plt.close()

    tsne = TSNE(n_components=2, random_state=seed, perplexity=max(5, min(30, len(df) // 10)))
    z = tsne.fit_transform(xs)
    plt.figure(figsize=(8, 6))
    plt.scatter(z[y == 0, 0], z[y == 0, 1], s=18, alpha=0.6, label="normal")
    plt.scatter(z[y == 1, 0], z[y == 1, 1], s=18, alpha=0.8, label="anomaly")
    plt.title("t-SNE: normal vs anomaly")
    plt.legend()
    plt.tight_layout()
    plt.savefig(PLOTS_DIR / "tsne_plot.png", dpi=140)
    plt.close()

    top = stats["feature"].head(8).tolist() if not stats.empty else features[:8]
    for f in top:
        plt.figure(figsize=(8, 5))
        plt.hist(df[df["label"] == 0][f].dropna(), bins=30, alpha=0.6, label="normal", density=True)
        plt.hist(df[df["label"] == 1][f].dropna(), bins=30, alpha=0.6, label="anomaly", density=True)
        plt.title(f"Feature distribution: {f}")
        plt.legend()
        plt.tight_layout()
        plt.savefig(PLOTS_DIR / f"hist_{f}.png", dpi=140)
        plt.close()

    nn = NearestNeighbors(n_neighbors=6).fit(xs)
    idx = nn.kneighbors(xs, return_distance=False)
    purity = np.array([np.mean(y[idx[i, 1:]] == y[i]) for i in range(len(y))])
    plt.figure(figsize=(8, 6))
    plt.scatter(pca[:, 0], pca[:, 1], c=purity, cmap="viridis", s=24, alpha=0.9)
    plt.colorbar(label="5-NN same-label purity")
    plt.title("Nearest-neighbor anomaly map")
    plt.tight_layout()
    plt.savefig(PLOTS_DIR / "nn_anomaly_map.png", dpi=140)
    plt.close()


def health_grade(stats: pd.DataFrame, nn: Dict[str, float], sup: Dict[str, Dict[str, float]], temporal: Dict[str, float], byte: Dict[str, float]) -> Tuple[str, float]:
    sep = float(stats["separability_score"].head(10).mean()) if not stats.empty else 0.0
    nn_score = (nn.get("anomaly_neighbor_purity", 0.0) + nn.get("normal_neighbor_purity", 0.0)) / 2.0
    rf = sup.get("random_forest", {})
    clf_score = (rf.get("f1", 0.0) + rf.get("roc_auc", 0.0)) / 2.0
    synth_penalty = 0.0
    if temporal.get("anomaly_frozen_frame_rate", 0.0) > 0.4:
        synth_penalty += 0.15
    if temporal.get("anomaly_repeated_payload_rate", 0.0) > 0.8:
        synth_penalty += 0.15
    total = max(0.0, min(1.0, (0.4 * sep) + (0.3 * clf_score) + (0.3 * nn_score) - synth_penalty))
    if total >= 0.70:
        return "GOOD", total
    if total >= 0.45:
        return "QUESTIONABLE", total
    return "WEAK", total


def write_report(path: Path, stats: pd.DataFrame, nn: Dict[str, float], sup: Dict[str, Dict[str, float]], temporal: Dict[str, float], byte: Dict[str, float], grade: str, score: float, sampled: pd.DataFrame) -> None:
    lines: List[str] = []
    lines.append("CAN DATASET AUDIT REPORT")
    lines.append("=" * 80)
    lines.append(f"Rows audited: {len(sampled)} (normal={int((sampled['label']==0).sum())}, anomaly={int((sampled['label']==1).sum())})")
    lines.append("")
    lines.append("STATISTICAL SEPARABILITY")
    lines.append("-" * 80)
    lines.append(stats.head(20).to_string(index=False))
    lines.append("")
    lines.append("NEAREST-NEIGHBOR PURITY")
    lines.append(str(nn))
    lines.append("")
    lines.append("SUPERVISED SANITY TEST")
    lines.append(str(sup))
    lines.append("")
    lines.append("TEMPORAL ANALYSIS")
    lines.append(str(temporal))
    lines.append("")
    lines.append("RAW BYTE ANALYSIS")
    lines.append(str(byte))
    lines.append("")
    lines.append("INTERPRETATION")
    lines.append("- anomalies statistically separable: " + ("yes" if (not stats.empty and stats['separability_score'].head(10).mean() > 0.5) else "weak"))
    rf = sup.get("random_forest", {})
    lines.append("- labels appear weak: " + ("yes" if rf.get("f1", 0) < 0.70 and rf.get("roc_auc", 0) < 0.75 else "no"))
    lines.append("- anomalies look synthetic: " + ("likely" if temporal.get("anomaly_frozen_frame_rate", 0) > 0.4 or temporal.get("anomaly_repeated_payload_rate", 0) > 0.8 else "not strongly indicated"))
    lines.append("- strongest discriminators: " + ", ".join(stats['feature'].head(8).tolist()))
    lines.append("- replay-like behavior risk: " + ("elevated" if temporal.get("anomaly_repeated_payload_rate", 0) > temporal.get("normal_repeated_payload_rate", 0) + 0.10 else "not elevated"))
    lines.append("- timing anomaly risk: " + ("elevated" if temporal.get("anomaly_periodicity_cv", 0) > temporal.get("normal_periodicity_cv", 0) * 1.25 else "not elevated"))
    lines.append("- frozen frame risk: " + ("elevated" if temporal.get("anomaly_frozen_frame_rate", 0) > temporal.get("normal_frozen_frame_rate", 0) + 0.05 else "not elevated"))
    if "state" in sampled.columns:
        st = sampled.groupby(["state", "label"]).size().unstack(fill_value=0)
        lines.append("- idle/parking/driving class balance:\n" + st.to_string())
    lines.append("")
    lines.append(f"FINAL DATASET HEALTH SCORE: {grade} (numeric={score:.3f})")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    configure_logging()
    args = parse_args()
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)

    df = load_dataset(Path(args.dataset))
    logger.info("Loaded dataset: %s rows, %s columns", len(df), len(df.columns))

    normal_s, anomaly_s = sample_classes(df, args.sample_size, args.seed)
    normal_s.to_csv(AUDIT_DIR / "audit_normal.csv", index=False)
    anomaly_s.to_csv(AUDIT_DIR / "audit_anomaly.csv", index=False)
    sampled = pd.concat([normal_s, anomaly_s], ignore_index=True)

    feats = get_numeric_features(sampled)
    logger.info("Using %d numeric features", len(feats))

    stats, ranking = describe_stats(normal_s, anomaly_s, feats)
    stats.to_csv(AUDIT_DIR / "feature_statistics.csv", index=False)
    ranking.to_csv(AUDIT_DIR / "feature_ranking.csv", index=False)
    if stats.empty:
        logger.warning("No valid numeric features had enough non-null rows for statistical audit.")
    else:
        logger.info("Top separability features:\n%s", stats[["feature", "separability_score", "cohens_d", "ks_stat", "overlap_estimate"]].head(15).to_string(index=False))

    nn = nearest_neighbor_purity(sampled, feats)
    sup = supervised_test(sampled, feats, args.seed)
    temporal = temporal_analysis(sampled)
    byte = byte_analysis(sampled)
    make_plots(sampled, stats, feats, args.seed)

    grade, numeric_score = health_grade(stats, nn, sup, temporal, byte)
    write_report(AUDIT_DIR / "audit_report.txt", stats, nn, sup, temporal, byte, grade, numeric_score, sampled)

    logger.info("Nearest-neighbor purity: %s", nn)
    logger.info("Supervised sanity metrics: %s", sup)
    logger.info("Temporal behavior summary: %s", temporal)
    logger.info("Raw byte summary: %s", byte)
    logger.info("FINAL DATASET HEALTH SCORE: %s (%.3f)", grade, numeric_score)
    print(f"FINAL DATASET HEALTH SCORE: {grade}")


if __name__ == "__main__":
    main()
