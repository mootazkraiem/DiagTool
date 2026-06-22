from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

BYTE_COLS = [f"b{i}" for i in range(8)]
KAGGLE_NORMAL_PATH = Path(__file__).resolve().parents[2] / "assets" / "archive" / "normal_run_data.txt"

FEATURE_COLS = [
    "time_diff",
    "rolling_std_time_diff",
    "rolling_mean_byte_diff",
    "rolling_byte_diff_std",
    "rolling_max_byte_diff",
    "rolling_min_byte_diff",
    "rolling_range_byte_diff",
    "msg_frequency",
    "byte_diff",
    "changed_bytes_count",
]


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    if any(col.startswith("byte_") for col in df.columns):
        raise ValueError("raw byte_ columns detected in input")

    required = ["timestamp", "can_id", *BYTE_COLS]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"missing required columns: {missing}")

    base = df[required].copy()
    # Detect padded/corrupted frames
    if "original_length" in df.columns:
        base["is_padded"] = (pd.to_numeric(df["original_length"], errors="coerce").fillna(8) < 8).astype(int)
    else:
        # Fallback heuristic: trailing bytes all zeros implies padded-like payload
        trailing_zero = (
            (pd.to_numeric(df.get("b7", 0), errors="coerce").fillna(0) == 0)
            & (pd.to_numeric(df.get("b6", 0), errors="coerce").fillna(0) == 0)
        )
        base["is_padded"] = trailing_zero.astype(int)
    base["timestamp"] = pd.to_numeric(base["timestamp"], errors="coerce")
    base["can_id"] = pd.to_numeric(base["can_id"], errors="coerce")
    for c in BYTE_COLS:
        base[c] = pd.to_numeric(base[c], errors="coerce")
    base = base.dropna().sort_values(["can_id", "timestamp"]).reset_index(drop=True)
    if base.empty:
        return pd.DataFrame(columns=["timestamp", "can_id", "is_padded", *FEATURE_COLS])

    # 1) compute raw features
    out = base.copy()
    out["time_diff"] = out.groupby("can_id")["timestamp"].diff().fillna(0.0)
    out["rolling_std_time_diff"] = (
        out.groupby("can_id")["time_diff"]
        .transform(lambda s: s.rolling(10, min_periods=1).std(ddof=0))
        .fillna(0.0)
    )

    prev_bytes = out.groupby("can_id")[BYTE_COLS].shift(1)
    byte_diff_mat = (out[BYTE_COLS] - prev_bytes).abs()
    out["byte_diff"] = byte_diff_mat.mean(axis=1).fillna(0.0)
    out["changed_bytes_count"] = (byte_diff_mat > 0).sum(axis=1).fillna(0.0)

    out["rolling_mean_byte_diff"] = (
        out.groupby("can_id")["byte_diff"]
        .transform(lambda s: s.rolling(10, min_periods=1).mean())
        .fillna(0.0)
    )
    out["rolling_byte_diff_std"] = (
        out.groupby("can_id")["byte_diff"]
        .transform(lambda s: s.rolling(10, min_periods=1).std(ddof=0))
        .fillna(0.0)
    )
    out["rolling_max_byte_diff"] = (
        out.groupby("can_id")["byte_diff"]
        .transform(lambda s: s.rolling(10, min_periods=1).max())
        .fillna(0.0)
    )
    out["rolling_min_byte_diff"] = (
        out.groupby("can_id")["byte_diff"]
        .transform(lambda s: s.rolling(10, min_periods=1).min())
        .fillna(0.0)
    )
    out["rolling_range_byte_diff"] = out["rolling_max_byte_diff"] - out["rolling_min_byte_diff"]
    out["msg_frequency"] = (
        out.groupby("can_id")["time_diff"]
        .transform(lambda s: 1.0 / (s.rolling(window=15, min_periods=1).mean() + 1e-3))
        .fillna(0.0)
    )

    # 2) clip
    out["time_diff"] = np.clip(out["time_diff"].to_numpy(dtype=np.float64), 0.0, 0.05)
    out["rolling_std_time_diff"] = np.clip(out["rolling_std_time_diff"].to_numpy(dtype=np.float64), 0.0, 0.05)
    out["rolling_mean_byte_diff"] = np.clip(out["rolling_mean_byte_diff"].to_numpy(dtype=np.float64), 0.0, 50.0)
    out["rolling_byte_diff_std"] = np.clip(out["rolling_byte_diff_std"].to_numpy(dtype=np.float64), 0.0, 50.0)
    out["rolling_max_byte_diff"] = np.clip(out["rolling_max_byte_diff"].to_numpy(dtype=np.float64), 0.0, 50.0)
    out["rolling_min_byte_diff"] = np.clip(out["rolling_min_byte_diff"].to_numpy(dtype=np.float64), 0.0, 50.0)
    out["rolling_range_byte_diff"] = np.clip(out["rolling_range_byte_diff"].to_numpy(dtype=np.float64), 0.0, 50.0)
    out["msg_frequency"] = np.clip(out["msg_frequency"].to_numpy(dtype=np.float64), 0.0, 100.0)
    out["byte_diff"] = np.clip(out["byte_diff"].to_numpy(dtype=np.float64), 0.0, 50.0)

    # 3) log transform
    out["time_diff"] = np.log1p(out["time_diff"])
    out["rolling_std_time_diff"] = np.log1p(out["rolling_std_time_diff"])
    out["rolling_mean_byte_diff"] = np.log1p(out["rolling_mean_byte_diff"])
    out["rolling_byte_diff_std"] = np.log1p(out["rolling_byte_diff_std"])
    out["rolling_max_byte_diff"] = np.log1p(out["rolling_max_byte_diff"])
    out["rolling_min_byte_diff"] = np.log1p(out["rolling_min_byte_diff"])
    out["rolling_range_byte_diff"] = np.log1p(out["rolling_range_byte_diff"])
    out["msg_frequency"] = np.log1p(out["msg_frequency"])
    out["byte_diff"] = np.log1p(out["byte_diff"])

    # 4) drop raw bytes only after feature creation
    out = out.drop(columns=BYTE_COLS, errors="ignore")

    out = out[["timestamp", "can_id", *FEATURE_COLS]].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return out


def normalize_per_can_id(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out[FEATURE_COLS] = out[FEATURE_COLS].astype(float)

    if out[FEATURE_COLS].isna().any(axis=None):
        print("[WARN] NaN detected before per-CAN-ID normalization")
    if not np.isfinite(out[FEATURE_COLS].to_numpy(dtype=np.float64)).all():
        print("[WARN] inf detected before per-CAN-ID normalization")

    for _, g in out.groupby("can_id", sort=False):
        x = g[FEATURE_COLS].to_numpy(dtype=np.float64, copy=True)
        mu = np.mean(x, axis=0)
        sd = np.std(x, axis=0)
        out.loc[g.index, FEATURE_COLS] = (x - mu) / (sd + 1e-6)

    out[FEATURE_COLS] = out[FEATURE_COLS].replace([np.inf, -np.inf], np.nan)
    if out[FEATURE_COLS].isna().any(axis=None):
        print("[WARN] NaN detected after per-CAN-ID normalization")
    out[FEATURE_COLS] = out[FEATURE_COLS].fillna(0.0)
    return out


def preprocess_pipeline(df: pd.DataFrame, scaler: object = None, fit: bool = False):
    from sklearn.preprocessing import RobustScaler

    feat_df = build_features(df)

    # Filter per CAN ID (keep only CAN IDs with temporal/content variation)
    valid_groups: list[pd.DataFrame] = []
    for can_id, group in feat_df.groupby("can_id", sort=False):
        if float(group["byte_diff"].std()) < 1e-6 and float(group["time_diff"].std()) < 1e-6:
            continue
        valid_groups.append(group)
    if not valid_groups:
        raise ValueError("All CAN IDs have zero variance")
    feat_df = pd.concat(valid_groups, ignore_index=True)
    print(feat_df.groupby("can_id")["byte_diff"].std().describe())

    # 4) normalize per can_id (after clip/log)
    feat_df = normalize_per_can_id(feat_df)
    X = feat_df[FEATURE_COLS].to_numpy(dtype=np.float64, copy=True)

    if feat_df.empty:
        raise ValueError("No usable training data after preprocessing")

    if fit:
        scaler = RobustScaler()
        X_scaled = scaler.fit_transform(X)
    else:
        if scaler is None:
            raise ValueError("scaler must be provided when fit=False")
        X_scaled = scaler.transform(X)

    if np.isnan(X_scaled).any():
        print("[WARN] NaN detected in scaled features")
    if np.isinf(X_scaled).any():
        print("[WARN] inf detected in scaled features")

    for i, name in enumerate(FEATURE_COLS):
        col = X_scaled[:, i]
        cmin = float(np.min(col))
        cmax = float(np.max(col))
        cmean = float(np.mean(col))
        cstd = float(np.std(col))
        print(f"[SANITY] {name}: min={cmin:.6f}, max={cmax:.6f}, mean={cmean:.6f}, std={cstd:.6f}")
        if abs(cmax) > 20 or abs(cmin) > 20:
            print(f"[WARNING] {name} abs(max) > 20")
        if cstd < 1e-8:
            print(f"[WARNING] {name} std ≈ 0")

    return feat_df, X_scaled, scaler


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    feat_df, _, _ = preprocess_pipeline(df, scaler=None, fit=True)
    return feat_df[["timestamp", "can_id", *FEATURE_COLS]]


def load_kaggle_dataset(path: str | Path) -> pd.DataFrame:
    raw_path = Path(path)
    lines = raw_path.read_text(encoding="utf-8", errors="replace").splitlines()
    raw = pd.DataFrame({"raw": lines}, dtype=str)

    pattern = r"Timestamp:\s*(?P<timestamp>[0-9]+\.[0-9]+)\s+ID:\s*(?P<can_id>[0-9A-Fa-f]+)\s+\S+\s+DLC:\s*(?P<dlc>\d+)\s+(?P<data>.+)"
    parsed = raw["raw"].str.extract(pattern)
    # Identify malformed rows
    bad_rows = parsed[parsed[['timestamp', 'can_id', 'data', 'dlc']].isna().any(axis=1)]
    # Check data validity: exactly 8 bytes, all valid hex
    def is_valid_data(data_str):
        if pd.isna(data_str):
            return False
        bytes_list = str(data_str).split()
        if len(bytes_list) != 8:
            return False
        try:
            for b in bytes_list:
                int(b, 16)
            return True
        except ValueError:
            return False
    parsed['valid_data'] = parsed['data'].apply(is_valid_data)
    bad_rows = pd.concat([bad_rows, parsed[~parsed['valid_data']]])
    bad_rows = bad_rows.drop_duplicates()
    if len(bad_rows) > 0:
        print(f"[WARNING] Skipping {len(bad_rows)} malformed rows")
        parsed = parsed.drop(bad_rows.index)
    parsed["data"] = parsed["data"].astype(str)
    bytes_expanded = parsed["data"].str.split(r"\s+", expand=True)
    for i in range(8):
        parsed[f"b{i}"] = bytes_expanded[i].apply(lambda x: int(x, 16))

    parsed["timestamp"] = parsed["timestamp"].astype(float)
    parsed["timestamp"] -= parsed["timestamp"].min()
    parsed["can_id"] = parsed["can_id"].astype(str)
    byte_cols = [f"b{i}" for i in range(8)]
    parsed = parsed.drop(columns=['valid_data'])
    return parsed[["timestamp", "can_id", *byte_cols]]


