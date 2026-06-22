from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Sequence

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

import sys

CURRENT_DIR = Path(__file__).resolve().parent
DATA_PROCESSING_DIR = CURRENT_DIR.parent / "data_processing"
if str(DATA_PROCESSING_DIR) not in sys.path:
    sys.path.append(str(DATA_PROCESSING_DIR))

from log_cleaner import load_all_logs
from feature_engineering import build_features


logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger("train_val_test_iforest")

FEATURE_COLS = [
    "time_diff",
    "freq",
    "byte_mean",
    "byte_std",
    "byte_min",
    "byte_max",
    "rolling_mean",
    "rolling_std",
    "entropy",
]

RANDOM_STATE = 42
MODEL_CLEAN_PATTERNS = ("*.pkl", "*.joblib")


def cleanup_model_artifacts(models_dir: Path) -> None:
    if not models_dir.exists():
        logger.info(f"[CLEANUP] models dir not found, skipping: {models_dir}")
        return

    removed = 0
    for pattern in MODEL_CLEAN_PATTERNS:
        for file_path in models_dir.glob(pattern):
            file_path.unlink(missing_ok=True)
            removed += 1
    logger.info(f"[CLEANUP] removed {removed} model artifact(s) from {models_dir}")


def load_data(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Split path not found: {path}")
    df = load_all_logs(str(path))
    if df.empty:
        raise ValueError(f"No valid log data found in: {path}")
    return df


def build_feature_set(df: pd.DataFrame) -> pd.DataFrame:
    features_df = build_features(df)
    missing = [col for col in FEATURE_COLS if col not in features_df.columns]
    if missing:
        raise ValueError(f"Missing feature columns after feature engineering: {missing}")
    features_df = features_df.replace([np.inf, -np.inf], np.nan).fillna(0)
    return features_df


def train_model(train_df: pd.DataFrame) -> tuple[IsolationForest, StandardScaler]:
    x_train = train_df.loc[:, FEATURE_COLS].to_numpy(dtype=np.float32, copy=False)

    scaler = StandardScaler()
    x_train_scaled = scaler.fit_transform(x_train)

    model = IsolationForest(
        n_estimators=100,
        contamination=0.01,
        random_state=RANDOM_STATE,
        n_jobs=-1,
    )
    model.fit(x_train_scaled)

    logger.info(f"[TRAIN] rows processed: {len(train_df):,}")
    return model, scaler


def evaluate_model(df: pd.DataFrame, model: IsolationForest, scaler: StandardScaler, stage: str) -> pd.DataFrame:
    x = df.loc[:, FEATURE_COLS].to_numpy(dtype=np.float32, copy=False)
    x_scaled = scaler.transform(x)

    labels = model.predict(x_scaled)
    scores = model.decision_function(x_scaled)

    out = df.copy()
    out["anomaly_label"] = labels
    out["anomaly_score"] = scores
    out["severity"] = -scores

    anomaly_ratio = float((out["anomaly_label"] == -1).mean() * 100.0)
    score_stats = out["anomaly_score"].describe(percentiles=[0.25, 0.5, 0.75])

    logger.info(f"[{stage}] anomaly ratio: {anomaly_ratio:.4f}%")
    logger.info(f"[{stage}] score distribution:\n{score_stats.to_string()}")
    return out


def plot_results(df: pd.DataFrame, stage: str, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    fig_hist, ax_hist = plt.subplots(figsize=(10, 5))
    ax_hist.hist(df["anomaly_score"].to_numpy(dtype=np.float32, copy=False), bins=80, color="steelblue", alpha=0.9)
    ax_hist.set_title(f"{stage} Anomaly Score Histogram")
    ax_hist.set_xlabel("Anomaly Score")
    ax_hist.set_ylabel("Count")
    ax_hist.grid(alpha=0.2)
    fig_hist.tight_layout()
    hist_path = output_dir / f"{stage.lower()}_anomaly_score_hist.png"
    fig_hist.savefig(hist_path, dpi=160)
    plt.close(fig_hist)

    x = df.loc[:, FEATURE_COLS].to_numpy(dtype=np.float32, copy=False)
    x_scaled = StandardScaler().fit_transform(x)
    x_pca = PCA(n_components=2, random_state=RANDOM_STATE).fit_transform(x_scaled)
    labels = df["anomaly_label"].to_numpy()

    normal_mask = labels == 1
    anomaly_mask = labels == -1

    fig_pca, ax_pca = plt.subplots(figsize=(10, 7))
    ax_pca.scatter(x_pca[normal_mask, 0], x_pca[normal_mask, 1], c="blue", s=5, alpha=0.45, label="Normal (1)", rasterized=True)
    ax_pca.scatter(x_pca[anomaly_mask, 0], x_pca[anomaly_mask, 1], c="red", s=12, alpha=0.85, label="Anomaly (-1)", rasterized=True)
    ax_pca.set_title(f"{stage} PCA Scatter (PC1 vs PC2)")
    ax_pca.set_xlabel("PC1")
    ax_pca.set_ylabel("PC2")
    ax_pca.grid(alpha=0.2)
    ax_pca.legend(loc="best")
    fig_pca.tight_layout()
    pca_path = output_dir / f"{stage.lower()}_pca_scatter.png"
    fig_pca.savefig(pca_path, dpi=160)
    plt.close(fig_pca)

    logger.info(f"[{stage}] saved plots: {hist_path.name}, {pca_path.name}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fresh Train/Validation/Test Isolation Forest pipeline.")
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path("log_files"),
        help="Root directory containing Train/, Validation/, Test/ folders.",
    )
    parser.add_argument(
        "--models-dir",
        type=Path,
        default=Path("models"),
        help="Directory for old model artifacts cleanup (pkl/joblib).",
    )
    parser.add_argument(
        "--plots-dir",
        type=Path,
        default=CURRENT_DIR / "results",
        help="Directory to save evaluation plots and CSV outputs.",
    )
    parser.add_argument(
        "--skip-cleanup",
        action="store_true",
        help="Skip startup cleanup of old model artifact files.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    data_root = args.data_root.resolve()
    models_dir = args.models_dir.resolve()
    plots_dir = args.plots_dir.resolve()

    if not args.skip_cleanup:
        cleanup_model_artifacts(models_dir)

    train_raw = load_data(data_root / "Train")
    val_raw = load_data(data_root / "Validation")
    test_raw = load_data(data_root / "Test")

    train_df = build_feature_set(train_raw)
    val_df = build_feature_set(val_raw)
    test_df = build_feature_set(test_raw)

    model, scaler = train_model(train_df)

    val_results = evaluate_model(val_df, model, scaler, stage="VALIDATION")
    test_results = evaluate_model(test_df, model, scaler, stage="TEST")

    plot_results(val_results, stage="VALIDATION", output_dir=plots_dir)
    plot_results(test_results, stage="TEST", output_dir=plots_dir)

    val_csv = plots_dir / "validation_results.csv"
    test_csv = plots_dir / "test_results.csv"
    val_results.to_csv(val_csv, index=False)
    test_results.to_csv(test_csv, index=False)

    logger.info(f"[VALIDATION] results saved: {val_csv}")
    logger.info(f"[TEST] results saved: {test_csv}")


if __name__ == "__main__":
    main()
