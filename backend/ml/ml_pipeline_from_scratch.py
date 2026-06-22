from __future__ import annotations

import logging
import time
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler


logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger("fast_ml_pipeline")

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

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CSV_ROOT = PROJECT_ROOT / "assets" / "processed_csv"
OUTPUT_ROOT = PROJECT_ROOT / "backend" / "ml" / "results"
MAX_TOTAL_ROWS = 100_000


def load_data(csv_root: Path = CSV_ROOT) -> pd.DataFrame:
    t0 = time.perf_counter()
    csv_files = [p for p in csv_root.rglob("*.csv") if p.is_file()]
    if not csv_files:
        raise RuntimeError(f"Run preprocess_mf4_to_csv.py first. No CSV files found in: {csv_root}")

    frames: list[pd.DataFrame] = []
    for file_path in csv_files:
        try:
            frames.append(pd.read_csv(file_path, low_memory=False))
        except Exception as exc:
            logger.warning(f"Skipped CSV: {file_path} | {exc}")

    if not frames:
        raise RuntimeError(f"Run preprocess_mf4_to_csv.py first. CSVs exist but none were readable in: {csv_root}")

    df = pd.concat(frames, ignore_index=True)
    if len(df) > MAX_TOTAL_ROWS:
        df = df.sample(n=MAX_TOTAL_ROWS, random_state=42)
    logger.info(f"Loading time: {time.perf_counter() - t0:.2f}s | Rows: {len(df):,}")
    return df


def _parse_hex_or_int(v: object) -> int:
    if pd.isna(v):
        return 0
    s = str(v).strip().lower()
    if not s:
        return 0
    try:
        if s.startswith("0x") or any(c in "abcdef" for c in s):
            return int(s, 16)
        return int(float(s))
    except Exception:
        return 0


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    t0 = time.perf_counter()
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    if "timestamp" not in df.columns:
        for alt in ("time", "index"):
            if alt in df.columns:
                df = df.rename(columns={alt: "timestamp"})
                break
    if "timestamp" not in df.columns:
        df["timestamp"] = np.arange(len(df), dtype=np.float64)
    if "can_id" not in df.columns:
        df["can_id"] = 0
    for i in range(8):
        col = f"b{i}"
        if col not in df.columns:
            df[col] = 0

    df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce").fillna(0.0)
    df["can_id"] = df["can_id"].apply(_parse_hex_or_int)
    byte_cols = [f"b{i}" for i in range(8)]
    for col in byte_cols:
        df[col] = df[col].apply(_parse_hex_or_int).clip(0, 255)

    df = df.drop_duplicates().sort_values(["can_id", "timestamp"]).reset_index(drop=True)
    df["time_diff"] = df.groupby("can_id")["timestamp"].diff().fillna(0.0)
    rolling_dt = df.groupby("can_id")["time_diff"].transform(lambda x: x.rolling(10, min_periods=1).mean())
    df["freq"] = (1.0 / rolling_dt.replace(0, np.nan)).fillna(0.0).replace([np.inf, -np.inf], 0.0)
    df["byte_mean"] = df[byte_cols].mean(axis=1)
    df["byte_std"] = df[byte_cols].std(axis=1).fillna(0.0)
    df["byte_min"] = df[byte_cols].min(axis=1)
    df["byte_max"] = df[byte_cols].max(axis=1)
    df["rolling_mean"] = df.groupby("can_id")["byte_mean"].transform(lambda x: x.rolling(10, min_periods=1).mean()).fillna(0.0)
    df["rolling_std"] = df.groupby("can_id")["byte_mean"].transform(lambda x: x.rolling(10, min_periods=1).std()).fillna(0.0)
    sorted_vals = np.sort(df[byte_cols].to_numpy(dtype=np.float32, copy=False), axis=1)
    df["entropy"] = (1 + np.sum(np.diff(sorted_vals, axis=1) > 0, axis=1)) / 8.0
    df = df.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    logger.info(f"Feature engineering time: {time.perf_counter() - t0:.2f}s")
    return df


def train_model(df: pd.DataFrame) -> tuple[IsolationForest, StandardScaler]:
    t0 = time.perf_counter()
    x = df[FEATURE_COLS].to_numpy(dtype=np.float32, copy=False)
    scaler = StandardScaler()
    x_scaled = scaler.fit_transform(x)
    model = IsolationForest(
        n_estimators=100,
        max_samples=10000,
        contamination=0.01,
        n_jobs=-1,
        random_state=42,
    )
    model.fit(x_scaled)
    logger.info(f"Training time: {time.perf_counter() - t0:.2f}s")
    return model, scaler


def detect_anomalies(df: pd.DataFrame, model: IsolationForest, scaler: StandardScaler) -> pd.DataFrame:
    out = df.copy()
    x = out[FEATURE_COLS].to_numpy(dtype=np.float32, copy=False)
    x_scaled = scaler.transform(x)
    out["anomaly_label"] = model.predict(x_scaled)
    out["anomaly_score"] = model.decision_function(x_scaled)
    return out


def plot_results(df: pd.DataFrame, out_dir: Path = OUTPUT_ROOT) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    fig1, ax1 = plt.subplots(figsize=(8, 4))
    ax1.hist(df["anomaly_score"], bins=60, color="steelblue", alpha=0.9)
    ax1.set_title("Anomaly Score Histogram")
    fig1.tight_layout()
    fig1.savefig(out_dir / "histogram.png", dpi=140)
    plt.close(fig1)

    x = df[FEATURE_COLS].to_numpy(dtype=np.float32, copy=False)
    x2 = PCA(n_components=2, random_state=42).fit_transform(StandardScaler().fit_transform(x))
    labels = df["anomaly_label"].to_numpy()
    fig2, ax2 = plt.subplots(figsize=(8, 5))
    ax2.scatter(x2[labels == 1, 0], x2[labels == 1, 1], s=5, alpha=0.35, c="blue", label="Normal")
    ax2.scatter(x2[labels == -1, 0], x2[labels == -1, 1], s=10, alpha=0.75, c="red", label="Anomaly")
    ax2.set_title("PCA 2D Scatter")
    ax2.legend()
    fig2.tight_layout()
    fig2.savefig(out_dir / "pca_plot.png", dpi=140)
    plt.close(fig2)


def main() -> None:
    df = load_data(CSV_ROOT)
    feat_df = build_features(df)
    model, scaler = train_model(feat_df)
    res_df = detect_anomalies(feat_df, model, scaler)
    plot_results(res_df, OUTPUT_ROOT)
    ratio = float((res_df["anomaly_label"] == -1).mean() * 100.0)
    logger.info(f"Done. Anomaly ratio: {ratio:.4f}%")


if __name__ == "__main__":
    main()
