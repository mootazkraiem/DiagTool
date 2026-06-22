from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import joblib
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from sklearn.decomposition import PCA
from sklearn.cluster import KMeans
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import RobustScaler
from sklearn.feature_selection import VarianceThreshold

try:
    from backend.ml.core.feature_engineering import load_kaggle_dataset, preprocess_pipeline
    from backend.ml.core.can_data_cleaning import clean_can_dataframe, CleaningConfig
    from backend.progress import print_progress
except ModuleNotFoundError:
    import sys
    sys.path.append(str(Path(__file__).resolve().parents[3]))
    from backend.ml.core.feature_engineering import load_kaggle_dataset, preprocess_pipeline
    from backend.ml.core.can_data_cleaning import clean_can_dataframe, CleaningConfig
    from backend.progress import print_progress

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ASSETS_ROOT = PROJECT_ROOT / "assets"
TRAIN_FEATURE_ROOT = ASSETS_ROOT / "processed_features" / "train"
MODEL_ROOT = ASSETS_ROOT / "models"
SCORE_DIST_ROOT = MODEL_ROOT / "score_distributions"
PCA_OUT_ROOT = PROJECT_ROOT / "outputs" / "pca"
KAGGLE_NORMAL_PATH = PROJECT_ROOT / "assets" / "archive" / "normal_run_data.txt"
STATE_NAMES = ["parking", "idle", "driving"]
MIN_ROWS_PER_STATE = 5000
ROBUST_K = 3.0
CONTAMINATION = 0.02
REQUIRED_FEATURES = [
    "time_diff",
    "rolling_std_time_diff",
    "rolling_mean_byte_diff",
    "rolling_byte_diff_std",
    "rolling_max_byte_diff",
    "msg_frequency",
    "byte_diff",
    "changed_bytes_count",
    "msg_rate",
    "rolling_var_time_diff",
    "burstiness",
    "can_id_entropy",
    # Attack-class-specific additions (added for richer attack representation)
    "payload_entropy",     # Shannon entropy of 8 frame bytes — separates Fuzzy (random) from normal
    "inter_arrival_cv",    # std/mean of inter-arrival time — separates DoS (uniform flood) from normal
]
STATE_FEATS = REQUIRED_FEATURES.copy()
FEATURES = REQUIRED_FEATURES.copy()


def _iter_csv(root: Path) -> Iterable[Path]:
    return sorted(p for p in root.rglob("*.csv") if p.is_file())


def _vehicle_from_path(path: Path, root: Path) -> str:
    rel = path.relative_to(root)
    return rel.parts[0].strip().lower().replace(" ", "_") if rel.parts else "unknown"


def _map_states(df: pd.DataFrame, labels: np.ndarray) -> dict[int, str]:
    tmp = df.copy()
    tmp["cluster"] = labels
    stats = tmp.groupby("cluster")[["rolling_std_time_diff", "byte_diff", "changed_bytes_count"]].mean()
    order = stats.sort_values(["rolling_std_time_diff", "byte_diff", "changed_bytes_count"]).index.tolist()
    return {order[0]: "parking", order[1]: "idle", order[2]: "driving"}


def _fit_state_models(df: pd.DataFrame, out_dir: Path) -> dict[str, float]:
    out_dir.mkdir(parents=True, exist_ok=True)
    thresholds: dict[str, float] = {}
    threshold_meta: dict[str, dict[str, float | str]] = {}
    feature_sets: dict[str, list[str]] = {}
    for state in STATE_NAMES:
        s_df = df[df["state"] == state]
        if len(s_df) < MIN_ROWS_PER_STATE:
            continue
        use_feats = [c for c in FEATURES if c in s_df.columns and c != "can_id" and not c.startswith("b") and float(s_df[c].std()) > 1e-6]
        assert not any(col.startswith("b") for col in use_feats)
        if len(use_feats) < 3:
            continue
        raw_x = s_df[use_feats].to_numpy(dtype=np.float32)
        selector = VarianceThreshold(threshold=1e-6)
        x_sel = selector.fit_transform(raw_x)
        support = selector.get_support()
        use_feats = [f for f, keep in zip(use_feats, support) if keep]
        if len(use_feats) < 3:
            continue
        scaler = RobustScaler()
        x = scaler.fit_transform(x_sel.astype(np.float32, copy=False))
        model = IsolationForest(n_estimators=200, contamination=CONTAMINATION, random_state=42, n_jobs=1)
        model.fit(x)
        scores = model.decision_function(x)
        median_score = float(np.median(scores))
        mad = float(np.median(np.abs(scores - median_score)))
        if mad < 1e-6:
            th = float(np.quantile(scores, 0.02))
            method = "p02_fallback_low_mad"
            print(f"[WARN] {out_dir.name}/{state}: MAD near zero, using percentile fallback")
        else:
            th = float(median_score - (ROBUST_K * mad))
            method = "median_minus_kmad"
        print(
            f"[INFO] {out_dir.name}/{state} "
            f"median={median_score:.6f} mad={mad:.6f} threshold={th:.6f} "
            f"min={float(np.min(scores)):.6f} max={float(np.max(scores)):.6f}"
        )
        joblib.dump(model, out_dir / f"model_{state}.joblib")
        joblib.dump(scaler, out_dir / f"scaler_{state}.joblib")
        thresholds[state] = th
        threshold_meta[state] = {
            "method": method,
            "k": ROBUST_K,
            "median_score": median_score,
            "mad": mad,
            "threshold": th,
            "score_min": float(np.min(scores)),
            "score_max": float(np.max(scores)),
        }
        feature_sets[state] = use_feats
        # Optional score histogram for debugging
        SCORE_DIST_ROOT.mkdir(parents=True, exist_ok=True)
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.hist(scores, bins=60, color="#2a9d8f", alpha=0.85)
        ax.axvline(th, color="#dc2626", linestyle="--", linewidth=2)
        ax.set_title(f"{out_dir.name} {state} score distribution")
        ax.set_xlabel("decision_function score")
        ax.set_ylabel("count")
        fig.tight_layout()
        fig.savefig(SCORE_DIST_ROOT / f"{out_dir.name}_{state}.png", dpi=120)
        plt.close(fig)
    (out_dir / "thresholds.json").write_text(json.dumps(thresholds, indent=2), encoding="utf-8")
    (out_dir / "threshold_meta.json").write_text(json.dumps(threshold_meta, indent=2), encoding="utf-8")
    (out_dir / "feature_sets.json").write_text(json.dumps(feature_sets, indent=2), encoding="utf-8")
    return thresholds


def _plot_pca(
    df: pd.DataFrame,
    model_dir: Path,
    label_prefix: str,
    sample_size: int = 10000,
) -> None:
    thresholds, feature_sets = _safe_load_state_artifacts(model_dir)
    if not thresholds or not feature_sets:
        return
    PCA_OUT_ROOT.mkdir(parents=True, exist_ok=True)

    for state in STATE_NAMES:
        model_path = model_dir / f"model_{state}.joblib"
        scaler_path = model_dir / f"scaler_{state}.joblib"
        if not (model_path.exists() and scaler_path.exists() and state in thresholds and state in feature_sets):
            continue

        sdf = df[df["state"] == state]
        if sdf.empty:
            continue
        if len(sdf) > sample_size:
            sdf = sdf.sample(n=sample_size, random_state=42)

        feats = feature_sets[state]
        if not all(c in sdf.columns for c in feats):
            continue

        model = joblib.load(model_path)
        scaler = joblib.load(scaler_path)
        x = sdf[feats].to_numpy(dtype=np.float32, copy=True)
        x_scaled = scaler.transform(x)
        scores = model.decision_function(x_scaled)
        labels = scores < float(thresholds[state])

        pca = PCA(n_components=2, random_state=42)
        comps = pca.fit_transform(x_scaled)

        fig, ax = plt.subplots(figsize=(9, 6))
        normal_mask = ~labels
        anomaly_mask = labels
        ax.scatter(comps[normal_mask, 0], comps[normal_mask, 1], s=8, alpha=0.35, c="#2563eb", label="normal")
        ax.scatter(comps[anomaly_mask, 0], comps[anomaly_mask, 1], s=12, alpha=0.8, c="#dc2626", label="anomaly")
        ax.set_title(f"{label_prefix} - {state}")
        ax.set_xlabel("PCA1")
        ax.set_ylabel("PCA2")
        ax.legend()
        ax.grid(alpha=0.2)
        fig.tight_layout()
        out_path = PCA_OUT_ROOT / f"pca_{label_prefix}_{state}.png"
        fig.savefig(out_path, dpi=150)
        plt.close(fig)


def train() -> None:
    MODEL_ROOT.mkdir(parents=True, exist_ok=True)
    if not KAGGLE_NORMAL_PATH.exists():
        raise FileNotFoundError(f"Kaggle normal dataset not found: {KAGGLE_NORMAL_PATH}")
    print_progress("TRAIN", "loading", 1, 1, KAGGLE_NORMAL_PATH.name)
    raw_df = load_kaggle_dataset(KAGGLE_NORMAL_PATH)
    raw_df = clean_can_dataframe(
        raw_df,
        output_dir=PROJECT_ROOT / "backend" / "ml" / "cleaning" / "train_normal",
        context="train_normal",
        config=CleaningConfig(min_can_occurrence=5, max_dt_quantile=0.999),
        apply_outlier_filter=True,
    )
    all_df, _x_scaled, _scaler = preprocess_pipeline(raw_df, scaler=None, fit=True)
    processed_out_path = PROJECT_ROOT / "backend" / "ml" / "processed_dataset.csv"
    all_df.to_csv(processed_out_path, index=False)
    print(f"[INFO] saved {processed_out_path}")
    if all_df.empty:
        raise ValueError("No usable training data after preprocessing")
    all_df["vehicle"] = "kaggle_normal"
    all_df = all_df.replace([np.inf, -np.inf], np.nan).fillna(0.0)

    # Global KMeans state detector
    print_progress("TRAIN", "kmeans", 1, 1, "fitting state clusters")
    state_scaler = RobustScaler()
    x_state = state_scaler.fit_transform(all_df[STATE_FEATS].to_numpy(dtype=np.float32))
    kmeans_model = KMeans(n_clusters=3, random_state=42, n_init=20)
    labels = kmeans_model.fit_predict(x_state)
    mapping = _map_states(all_df, labels)
    all_df["state"] = pd.Series(labels).map(mapping)
    joblib.dump(state_scaler, MODEL_ROOT / "state_scaler.joblib")
    joblib.dump(kmeans_model, MODEL_ROOT / "kmeans_state_model.joblib")
    (MODEL_ROOT / "state_mapping.json").write_text(json.dumps({str(k): v for k, v in mapping.items()}, indent=2), encoding="utf-8")
    print()

    # General models
    print_progress("TRAIN", "general", 1, 1, "fitting general state models")
    general_dir = MODEL_ROOT / "general"
    _fit_state_models(all_df, general_dir)
    print()

    # Vehicle-specific models
    vehicle_groups = list(all_df.groupby("vehicle", sort=False))
    total_vehicles = len(vehicle_groups)
    for idx, (vehicle, vdf) in enumerate(vehicle_groups, start=1):
        can_ids = vdf["can_id"].unique()
        print_progress("TRAIN", vehicle, idx, total_vehicles, f"{len(can_ids)} CAN IDs")
        _fit_state_models(vdf, MODEL_ROOT / vehicle)
    print()

    # PCA diagnostics
    print_progress("TRAIN", "pca", 1, 1, "generating diagnostics")
    _plot_pca(all_df, general_dir, "general")
    for vehicle, vdf in all_df.groupby("vehicle", sort=False):
        _plot_pca(vdf, MODEL_ROOT / vehicle, vehicle)
    print()


    print("[INFO] state models trained under assets/models")


def _safe_load_state_artifacts(root: Path) -> tuple[dict[str, float], dict[str, list[str]]]:
    th = {}
    fs = {}
    th_path = root / "thresholds.json"
    fs_path = root / "feature_sets.json"
    if th_path.exists():
        th = json.loads(th_path.read_text(encoding="utf-8"))
    if fs_path.exists():
        fs = json.loads(fs_path.read_text(encoding="utf-8"))
    return th, fs


def infer(df_features: pd.DataFrame, vehicle: str) -> pd.DataFrame:
    vehicle_key = vehicle.strip().lower().replace(" ", "_")
    out = df_features.copy()
    for c in STATE_FEATS:
        if c not in out.columns:
            out[c] = 0.0
    out[STATE_FEATS] = out[STATE_FEATS].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    state_scaler = joblib.load(MODEL_ROOT / "state_scaler.joblib")
    kmeans_model = joblib.load(MODEL_ROOT / "kmeans_state_model.joblib")
    mapping = {int(k): v for k, v in json.loads((MODEL_ROOT / "state_mapping.json").read_text(encoding="utf-8")).items()}
    x_state = state_scaler.transform(out[STATE_FEATS].to_numpy(dtype=np.float32))
    labels = kmeans_model.predict(x_state)
    out["state"] = [mapping[int(c)] for c in labels]
    out["anomaly_score"] = 0.0
    out["smoothed_score"] = 0.0
    out["is_anomaly"] = 0

    general_dir = MODEL_ROOT / "general"
    vehicle_dir = MODEL_ROOT / vehicle_key
    g_th, g_fs = _safe_load_state_artifacts(general_dir)
    v_th, v_fs = _safe_load_state_artifacts(vehicle_dir)

    for state in STATE_NAMES:
        mask = out["state"] == state
        if not mask.any():
            continue
        use_vehicle = (
            (vehicle_dir / f"model_{state}.joblib").exists()
            and (vehicle_dir / f"scaler_{state}.joblib").exists()
            and state in v_th
            and state in v_fs
        )
        chosen = vehicle_dir if use_vehicle else general_dir
        th_map = v_th if use_vehicle else g_th
        fs_map = v_fs if use_vehicle else g_fs
        if not ((chosen / f"model_{state}.joblib").exists() and (chosen / f"scaler_{state}.joblib").exists() and state in th_map and state in fs_map):
            # safe fallback: if neither exists, keep normal
            print(f"[STATE] {state}")
            print(f"[VEHICLE] {vehicle_key}")
            print("[MODEL USED] none")
            continue
        model = joblib.load(chosen / f"model_{state}.joblib")
        scaler = joblib.load(chosen / f"scaler_{state}.joblib")
        feats = fs_map[state]
        for c in feats:
            if c not in out.columns:
                out[c] = 0.0
        assert not any(col.startswith("b") for col in feats)
        x = out.loc[mask, feats].to_numpy(dtype=np.float32)
        scores = model.decision_function(scaler.transform(x))
        threshold = float(th_map[state])
        smoothed = pd.Series(scores).rolling(5, min_periods=1).mean().to_numpy()
        below = smoothed < threshold
        persistent = (
            pd.Series(below.astype(np.int8))
            .rolling(5, min_periods=1)
            .sum()
            .to_numpy() >= 3
        )
        out.loc[mask, "anomaly_score"] = scores
        out.loc[mask, "smoothed_score"] = smoothed
        out.loc[mask, "is_anomaly"] = persistent.astype(np.int8)
        if len(smoothed) > 0:
            print(
                f"[DEBUG] {vehicle_key}/{state} "
                f"smoothed={float(smoothed[-1]):.6f} "
                f"threshold={threshold:.6f} "
                f"decision={'anomaly' if bool(persistent[-1]) else 'normal'}"
            )
        print(f"[STATE] {state}")
        print(f"[VEHICLE] {vehicle_key}")
        print(f"[MODEL USED] {'vehicle' if use_vehicle else 'general'}")
    return out


if __name__ == "__main__":
    train()
