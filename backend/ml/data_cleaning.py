from __future__ import annotations

import re
from pathlib import Path
import sys

import numpy as np
import pandas as pd

try:
    from backend.progress import print_progress
except ModuleNotFoundError:
    sys.path.append(str(Path(__file__).resolve().parents[2]))
    from backend.progress import print_progress

ASSETS_ROOT = Path(__file__).resolve().parents[2] / "assets"
RAW_ROOT_CANDIDATES = [
    ASSETS_ROOT / "Train",

]
CLEAN_ROOT = Path(__file__).resolve().parents[2] / "assets" / "clean_traincsv"
BYTE_COLS = [f"b{i}" for i in range(8)]


def _resolve_raw_root() -> Path:
    for candidate in RAW_ROOT_CANDIDATES:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "no train data folder found (checked:  Train)"
    )


def _parse_data_bytes(value: object) -> list[int]:
    if pd.isna(value):
        return [0] * 8

    values: list[int] = []
    try:
        if isinstance(value, (bytes, bytearray)):
            values = list(value)
        elif isinstance(value, str):
            tokens = re.findall(r"0x[0-9a-fA-F]+|\d+", value)
            for token in tokens:
                values.append(int(token, 16) if token.lower().startswith("0x") else int(token))
        elif isinstance(value, (list, tuple, np.ndarray)):
            values = [int(x) for x in value]
        else:
            values = [int(value)]
    except Exception:
        values = []

    if len(values) < 8:
        values += [0] * (8 - len(values))
    else:
        values = values[:8]

    cleaned: list[int] = []
    for x in values:
        try:
            cleaned.append(max(0, min(255, int(x))))
        except Exception:
            cleaned.append(0)
    return cleaned


def clean_single_csv(input_path: Path, output_path: Path) -> int:
    df = pd.read_csv(input_path, low_memory=False)

    if "timestamps" in df.columns:
        df["timestamp"] = df["timestamps"]
    elif "timestamp" not in df.columns:
        df["timestamp"] = np.arange(len(df), dtype=np.float64)

    bytes_col = "CAN_DataFrame.CAN_DataFrame.DataBytes"
    if bytes_col in df.columns:
        parsed = df[bytes_col].apply(_parse_data_bytes)
        byte_df = pd.DataFrame(parsed.tolist(), columns=BYTE_COLS, index=df.index)
        df = pd.concat([df, byte_df], axis=1)

    if "can_id" not in df.columns:
        df["can_id"] = np.nan

    for col in BYTE_COLS:
        if col not in df.columns:
            df[col] = np.nan

    df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce")
    df["can_id"] = pd.to_numeric(df["can_id"], errors="coerce")
    for col in BYTE_COLS:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    keep_cols = ["timestamp", "can_id", *BYTE_COLS]
    df = df[keep_cols].dropna()
    if df.empty:
        return 0

    df["timestamp"] = df["timestamp"].astype(np.float64)
    df["can_id"] = df["can_id"].astype(np.int64)
    for col in BYTE_COLS:
        df[col] = df[col].clip(0, 255).astype(np.int16)

    df = df.sort_values("timestamp").drop_duplicates().reset_index(drop=True)
    df["time_diff"] = df.groupby("can_id")["timestamp"].diff().fillna(0)
    negative_time = df["time_diff"] < 0
    if negative_time.any():
        df = df.loc[~negative_time].reset_index(drop=True)

    if df.empty:
        return 0

    df["byte_std"] = df[BYTE_COLS].std(axis=1).fillna(0)
    sorted_vals = np.sort(df[BYTE_COLS].to_numpy(dtype=np.float64, copy=False), axis=1)
    df["entropy"] = (1 + np.sum(np.diff(sorted_vals, axis=1) > 0, axis=1)) / 8.0

    group_stats = df.groupby("can_id").agg(
        rows=("timestamp", "size"),
        byte_std_mean=("byte_std", "mean"),
        entropy_mean=("entropy", "mean"),
    )

    keep_ids = group_stats[
        (group_stats["rows"] >= 200)
        & (group_stats["byte_std_mean"] >= 1.0)
        & (group_stats["entropy_mean"] >= 0.1)
    ].index

    df = df[df["can_id"].isin(keep_ids)]
    df = df.groupby("can_id", group_keys=False).head(50000).reset_index(drop=True)
    df = df[keep_cols]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)

    return len(df)


def _is_clean_output_current(input_path: Path, output_path: Path) -> bool:
    if not output_path.exists() or output_path.stat().st_size == 0:
        return False
    return output_path.stat().st_mtime >= input_path.stat().st_mtime


def main() -> None:
    try:
        raw_root = _resolve_raw_root()
    except FileNotFoundError as exc:
        print(f"[ERROR] {exc}")
        return

    csv_files = sorted([p for p in raw_root.rglob("*.csv") if p.is_file()])
    print(f"Found {len(csv_files)} raw CSV files")

    total_rows = 0
    total = len(csv_files)
    for idx, src in enumerate(csv_files, start=1):
        print_progress("CLEAN", "train", idx, total, src.name)
        rel = src.relative_to(raw_root)
        dst = CLEAN_ROOT / rel
        try:
            if _is_clean_output_current(src, dst):
                continue
            output_rows = clean_single_csv(src, dst)
            total_rows += output_rows
            if output_rows == 0:
                print()
                print(f"[WARN][CLEAN] {src.name} -> 0 valid rows")
        except Exception as exc:
            print()
            print(f"[ERROR][CLEAN] {src} ({exc})")

    print()
    print(f"Cleaned rows written: {total_rows}")
    print(f"Output folder: {CLEAN_ROOT}")


if __name__ == "__main__":
    main()
