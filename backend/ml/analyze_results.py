from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from pandas.plotting import scatter_matrix
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler


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

DEFAULT_INPUT_PATH = Path(__file__).resolve().parent / "results" / "isolation_results.csv"
REQUIRED_COLUMNS = {"timestamp", "can_id", "anomaly_label", "anomaly_score", "severity"}
MAX_PLOT_ROWS = 50_000
SAMPLE_THRESHOLD = 100_000


def anomaly_ratio(df: pd.DataFrame) -> tuple[int, int, float]:
    total_rows = len(df)
    anomaly_count = int((df["anomaly_label"] == -1).sum())
    anomaly_pct = (anomaly_count / total_rows * 100.0) if total_rows else 0.0
    print("=== Anomaly Ratio ===")
    print(f"Total rows: {total_rows:,}")
    print(f"Anomaly rows: {anomaly_count:,}")
    print(f"Anomaly percentage: {anomaly_pct:.4f}%")
    print()
    return total_rows, anomaly_count, anomaly_pct


def score_distribution(df: pd.DataFrame) -> pd.Series:
    stats = df["anomaly_score"].describe(percentiles=[0.25, 0.5, 0.75])
    print("=== Anomaly Score Distribution ===")
    print(stats.to_string())
    print()
    return stats


def list_anomalies(df: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
    anomaly_df = df.loc[df["anomaly_label"] == -1, ["timestamp", "can_id", "anomaly_score", "severity"]]
    top_anomalies = anomaly_df.nsmallest(top_n, columns="anomaly_score")
    print(f"=== Top {top_n} Anomalies ===")
    if top_anomalies.empty:
        print("No anomalies found.")
    else:
        print(top_anomalies.to_string(index=False))
    print()
    return top_anomalies


def _prepare_scaled_features(df: pd.DataFrame, feature_cols: Sequence[str]) -> np.ndarray:
    x = df.loc[:, feature_cols].to_numpy(dtype=np.float32, copy=False)
    scaler = StandardScaler(copy=False)
    return scaler.fit_transform(x)


def _sample_for_plotting(df: pd.DataFrame, random_state: int = 42) -> pd.DataFrame:
    if len(df) > SAMPLE_THRESHOLD:
        return df.sample(n=MAX_PLOT_ROWS, random_state=random_state)
    return df


def plot_pca_variance(df: pd.DataFrame, feature_cols: Sequence[str]) -> None:
    x_scaled = _prepare_scaled_features(df, feature_cols)
    n_components = len(feature_cols)
    pca = PCA(n_components=n_components, random_state=42)
    pca.fit(x_scaled)

    explained = pca.explained_variance_ratio_
    cumulative = np.cumsum(explained)
    pc_idx = np.arange(1, n_components + 1, dtype=np.int32)

    print("=== PCA Explained Variance ===")
    for idx, (ev, cum) in enumerate(zip(explained, cumulative), start=1):
        print(f"PC{idx}: explained={ev:.4%}, cumulative={cum:.4%}")
    print()

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(pc_idx, cumulative, marker="o", linewidth=2, color="teal", label="Cumulative explained variance")
    ax.set_xticks(pc_idx)
    ax.set_ylim(0.0, 1.02)
    ax.set_xlabel("Principal Component")
    ax.set_ylabel("Cumulative Explained Variance")
    ax.set_title("PCA Cumulative Explained Variance")
    ax.grid(alpha=0.25)
    ax.legend(loc="lower right")
    fig.tight_layout()


def plot_pca_views(df: pd.DataFrame, feature_cols: Sequence[str], random_state: int = 42) -> None:
    sampled_df = _sample_for_plotting(df, random_state=random_state)
    x_scaled = _prepare_scaled_features(sampled_df, feature_cols)
    pca = PCA(n_components=3, random_state=random_state)
    x_3d = pca.fit_transform(x_scaled)

    labels = sampled_df["anomaly_label"].to_numpy()
    normal_mask = labels == 1
    anomaly_mask = labels == -1

    projection_pairs = [(0, 1), (0, 2), (1, 2)]
    titles = ["PC1 vs PC2", "PC1 vs PC3", "PC2 vs PC3"]

    fig, axes = plt.subplots(1, 3, figsize=(18, 5))
    for ax, (i, j), title in zip(axes, projection_pairs, titles):
        ax.scatter(x_3d[normal_mask, i], x_3d[normal_mask, j], c="blue", s=5, alpha=0.45, label="Normal (1)", rasterized=True)
        ax.scatter(x_3d[anomaly_mask, i], x_3d[anomaly_mask, j], c="red", s=10, alpha=0.8, label="Anomaly (-1)", rasterized=True)
        ax.set_xlabel(f"PC{i + 1}")
        ax.set_ylabel(f"PC{j + 1}")
        ax.set_title(f"PCA Projection: {title}")
        ax.grid(alpha=0.2)

    handles, labels_legend = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels_legend, loc="upper center", ncol=2)
    fig.tight_layout(rect=[0, 0, 1, 0.93])


def plot_feature_scatter_matrix(df: pd.DataFrame, feature_cols: Sequence[str], random_state: int = 42) -> None:
    selected_features = list(feature_cols[:5])
    sampled_df = _sample_for_plotting(df, random_state=random_state)
    matrix_df = sampled_df.loc[:, selected_features].copy()
    matrix_df["label_name"] = np.where(sampled_df["anomaly_label"].to_numpy() == -1, "Anomaly", "Normal")
    color_map = {"Normal": "blue", "Anomaly": "red"}
    colors = matrix_df["label_name"].map(color_map).to_numpy()

    axes = scatter_matrix(
        matrix_df[selected_features],
        figsize=(12, 12),
        diagonal="hist",
        c=colors,
        alpha=0.25,
        s=6,
        marker="o",
        rasterized=True,
    )
    fig = axes[0, 0].figure
    fig.suptitle("Feature Scatter Matrix (Sampled)")
    fig.tight_layout(rect=[0, 0, 1, 0.97])


def plot_pca_3d(df: pd.DataFrame, feature_cols: Sequence[str], random_state: int = 42) -> None:
    sampled_df = _sample_for_plotting(df, random_state=random_state)
    x_scaled = _prepare_scaled_features(sampled_df, feature_cols)
    pca = PCA(n_components=3, random_state=random_state)
    x_3d = pca.fit_transform(x_scaled)

    labels = sampled_df["anomaly_label"].to_numpy()
    normal_mask = labels == 1
    anomaly_mask = labels == -1

    fig = plt.figure(figsize=(10, 7))
    ax = fig.add_subplot(111, projection="3d")
    ax.scatter(x_3d[normal_mask, 0], x_3d[normal_mask, 1], x_3d[normal_mask, 2], c="blue", s=4, alpha=0.35, label="Normal (1)", rasterized=True)
    ax.scatter(x_3d[anomaly_mask, 0], x_3d[anomaly_mask, 1], x_3d[anomaly_mask, 2], c="red", s=12, alpha=0.85, label="Anomaly (-1)", rasterized=True)
    ax.set_title("3D PCA Projection (PC1, PC2, PC3)")
    ax.set_xlabel("PC1")
    ax.set_ylabel("PC2")
    ax.set_zlabel("PC3")
    ax.legend(loc="best")
    fig.tight_layout()


def plot_anomaly_score_histogram(df: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.hist(df["anomaly_score"].to_numpy(dtype=np.float32, copy=False), bins=80, color="steelblue", alpha=0.9)
    ax.set_title("Anomaly Score Histogram")
    ax.set_xlabel("Anomaly Score")
    ax.set_ylabel("Count")
    ax.grid(alpha=0.2)
    fig.tight_layout()


def validate_columns(df: pd.DataFrame, feature_cols: Sequence[str]) -> None:
    expected = REQUIRED_COLUMNS.union(feature_cols)
    missing = sorted(col for col in expected if col not in df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {missing}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Post-process and visualize Isolation Forest anomaly results.")
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help=f"Path to results CSV (default: {DEFAULT_INPUT_PATH})",
    )
    parser.add_argument(
        "--no-hist",
        action="store_true",
        help="Disable anomaly_score histogram plot.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_path = args.input

    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    df = pd.read_csv(input_path, low_memory=False)
    validate_columns(df, FEATURE_COLS)

    anomaly_ratio(df)
    score_distribution(df)
    list_anomalies(df, top_n=10)
    plot_pca_variance(df, FEATURE_COLS)
    plot_pca_views(df, FEATURE_COLS)
    plot_feature_scatter_matrix(df, FEATURE_COLS)
    plot_pca_3d(df, FEATURE_COLS)
    if not args.no_hist:
        plot_anomaly_score_histogram(df)
    plt.show()


if __name__ == "__main__":
    main()
