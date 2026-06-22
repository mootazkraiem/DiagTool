from __future__ import annotations

from pathlib import Path
from typing import Iterable
import sys

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

try:
    from backend.data_processing.mf4_to_csv_converter import run_mf4_conversion
    from backend.ml.feature_engineering import run_feature_engineering
except ModuleNotFoundError:
    sys.path.append(str(Path(__file__).resolve().parents[2]))
    from backend.data_processing.mf4_to_csv_converter import run_mf4_conversion
    from backend.ml.feature_engineering import run_feature_engineering

FEATURE_ROOT = Path(__file__).resolve().parents[2] / "assets" / "processed_features" / "train"
MODEL_ROOT = Path(__file__).resolve().parents[2] / "assets" / "models"

FEATURE_COLS = [
    "time_diff", "freq", "byte_mean", "byte_std", "byte_min",
    "byte_max", "rolling_mean", "rolling_std", "entropy",
]


def _vehicle_name_from_path(path: Path, root: Path) -> str:
    relative_path = path.relative_to(root)
    return relative_path.parts[0] if relative_path.parts else "unknown"


def iter_feature_files() -> Iterable[Path]:
    yield from sorted(p for p in FEATURE_ROOT.rglob("*.csv") if p.is_file())


def train_per_can_id() -> int:
    MODEL_ROOT.mkdir(parents=True, exist_ok=True)
    trained = 0
    data_by_vehicle: dict[str, dict[object, list[np.ndarray]]] = {}

    for csv_path in iter_feature_files():
        vehicle_name = _vehicle_name_from_path(csv_path, FEATURE_ROOT)
        df = pd.read_csv(csv_path, low_memory=False)
        if df.empty or "can_id" not in df.columns:
            continue

        missing_cols = [c for c in FEATURE_COLS if c not in df.columns]
        if missing_cols:
            continue

        for can_id, group in df.groupby("can_id", sort=False):
            x = group[FEATURE_COLS].to_numpy(dtype=np.float32, copy=False)
            if x.size == 0:
                continue
            data_by_vehicle.setdefault(vehicle_name, {}).setdefault(can_id, []).append(x)

    for vehicle_name, vehicle_data in sorted(data_by_vehicle.items()):
        vehicle_dir = MODEL_ROOT / vehicle_name
        vehicle_dir.mkdir(parents=True, exist_ok=True)
        print(f"[INFO] Vehicle: {vehicle_name}")

        for can_id, arrays in sorted(vehicle_data.items(), key=lambda kv: str(kv[0])):
            x = np.vstack(arrays)
            if len(x) < 20:
                continue

            scaler = StandardScaler()
            x_scaled = scaler.fit_transform(x)

            model = IsolationForest(
                n_estimators=100,
                contamination=0.01,
                random_state=42,
                n_jobs=1,
            )
            model.fit(x_scaled)

            safe_id = str(int(can_id)) if pd.notna(can_id) else "unknown"
            joblib.dump(model, vehicle_dir / f"iforest_canid_{safe_id}.joblib")
            joblib.dump(scaler, vehicle_dir / f"scaler_canid_{safe_id}.joblib")
            trained += 1

        print(f"[INFO] Models saved to: {vehicle_dir}")

    return trained


def main() -> None:
    run_mf4_conversion("train")
    run_feature_engineering("train")

    feature_files = list(iter_feature_files())
    if not feature_files:
        print(f"No processed feature files found in: {FEATURE_ROOT}")
        return

    trained_count = train_per_can_id()
    rows = sum(
        pd.read_csv(path, low_memory=False).shape[0]
        for path in feature_files
    )
    print(f"Loaded {rows} feature rows from {len(feature_files)} files")
    print(f"Trained models: {trained_count}")
    print(f"Models saved to: {MODEL_ROOT}")


if __name__ == "__main__":
    main()
