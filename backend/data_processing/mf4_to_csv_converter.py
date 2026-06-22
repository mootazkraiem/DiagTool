from __future__ import annotations

import csv
import re
from collections.abc import Iterable
from pathlib import Path

from asammdf import MDF

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATASET_CONFIG: dict[str, tuple[list[Path], Path]] = {
    "train": (
        [
            PROJECT_ROOT / "assets" / "train_mf4",
            PROJECT_ROOT / "assets" / "Train",
        ],
        PROJECT_ROOT / "assets" / "train_csv",
    ),
    "validation": (
        [
            PROJECT_ROOT / "assets" / "Validation",
            PROJECT_ROOT / "assets" / "validation_mf4",
        ],
        PROJECT_ROOT / "assets" / "validation_csv",
    ),
    "test": (
        [
            PROJECT_ROOT / "assets" / "test_mf4",
            PROJECT_ROOT / "assets" / "Test",
        ],
        PROJECT_ROOT / "assets" / "test_csv",
    ),
}

CSV_HEADER = ["timestamp", "can_id", "b0", "b1", "b2", "b3", "b4", "b5", "b6", "b7"]


def _resolve_source_root(dataset_type: str) -> tuple[Path, Path]:
    source_candidates, output_root = DATASET_CONFIG[dataset_type]
    for candidate in source_candidates:
        if candidate.exists():
            return candidate, output_root
    raise FileNotFoundError(f"no source folder found for '{dataset_type}'")


def _discover_mf4_files(source_root: Path) -> list[Path]:
    files = list(source_root.rglob("*.MF4")) + list(source_root.rglob("*.mf4"))
    return sorted(set(files), key=lambda p: str(p))


def _is_csv_valid(csv_path: Path) -> bool:
    try:
        if not csv_path.exists() or csv_path.stat().st_size == 0:
            return False
        with csv_path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            first_row = next(reader, None)
        return header == CSV_HEADER and first_row is not None and len(first_row) == len(CSV_HEADER)
    except Exception:
        return False


def _normalize_can_id(value: object) -> int:
    text = str(value).strip()
    if text.lower().startswith("0x"):
        return int(text, 16)
    return int(float(text))


def _parse_data_bytes(value: object) -> tuple[list[int], bool]:
    corrected = False
    out: list[object] = []

    try:
        if value is None:
            corrected = True
        elif isinstance(value, str):
            tokens = re.findall(r'0x[0-9a-fA-F]+|\d+', value)
            out = [
                int(tok, 16) if tok.lower().startswith("0x") else int(tok)
                for tok in tokens
            ]
            if len(out) != 8:
                corrected = True
        elif isinstance(value, (bytes, bytearray)):
            out = list(value)
            if len(out) != 8:
                corrected = True
        elif isinstance(value, Iterable):
            out = list(value)
            if len(out) != 8:
                corrected = True
        else:
            out = [int(value)]
    except Exception:
        out = []
        corrected = True

    normalized: list[int] = []
    for item in out[:8]:
        try:
            byte_value = int(item)
            normalized.append(max(0, min(255, byte_value)))
        except Exception:
            normalized.append(0)
            corrected = True

    if len(normalized) < 8:
        corrected = True
        normalized.extend([0] * (8 - len(normalized)))

    return normalized, corrected


def _extract_raw_rows(mf4_path: Path) -> Iterable[tuple[list[object], bool]]:
    mdf = MDF(str(mf4_path))
    df = mdf.to_dataframe()

    cols = list(df.columns)

    # 🔥 Safe column filtering (with fallback)
    filtered_cols = []
    for c in cols:
        c_low = str(c).lower()
        if (
            "id" in c_low
            or "data" in c_low
            or "byte" in c_low
            or "time" in c_low
        ):
            filtered_cols.append(c)

    if len(filtered_cols) >= 2:
        df = df[filtered_cols]

    cols = list(df.columns)
    lower_map = {str(c).lower(): c for c in cols}

    ts_col = None
    for key in ("timestamps", "timestamp", "time"):
        if key in lower_map:
            ts_col = lower_map[key]
            break

    id_col = None
    bytes_col = None

    for c in cols:
        c_low = str(c).lower()
        if id_col is None and ("id" in c_low):
            id_col = c
        if bytes_col is None and ("data" in c_low or "byte" in c_low):
            bytes_col = c

    if id_col is None or bytes_col is None:
        raise ValueError(f"missing CAN columns; available columns: {cols[:20]}")

    if ts_col is not None:
        iterator = df[[ts_col, id_col, bytes_col]].itertuples(index=False, name=None)
    else:
        iterator = (
            (idx, r[0], r[1])
            for idx, r in zip(df.index, df[[id_col, bytes_col]].itertuples(index=False, name=None))
        )

    for timestamp, can_id_raw, data_bytes_raw in iterator:
        try:
            can_id = _normalize_can_id(can_id_raw)
            b, corrected = _parse_data_bytes(data_bytes_raw)
            yield [float(timestamp), can_id, *b], corrected
        except Exception:
            continue


def _convert_one_file(mf4_path: Path, csv_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    BATCH_SIZE = 10000
    malformed = False

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADER)

        batch = []

        for row, corrected in _extract_raw_rows(mf4_path):
            batch.append(row)
            if corrected:
                malformed = True

            if len(batch) >= BATCH_SIZE:
                writer.writerows(batch)
                batch.clear()

        if batch:
            writer.writerows(batch)

    if malformed:
        print()
        print(f"[WARN] {mf4_path.name}: corrected malformed DataBytes")


def run_mf4_conversion(dataset_type: str, force: bool = False) -> None:
    if dataset_type not in DATASET_CONFIG:
        raise ValueError("dataset_type must be one of {'train', 'validation', 'test'}")

    try:
        source_root, output_root = _resolve_source_root(dataset_type)
    except FileNotFoundError as exc:
        print(f"[ERROR] dataset '{dataset_type}' ({exc})")
        return

    print(f"[INFO] dataset: {dataset_type}")
    mf4_files = _discover_mf4_files(source_root)

    if not mf4_files:
        print(f"[INFO] no MF4 files found in {source_root}")
        return

    total_files = len(mf4_files)

    for idx, mf4_path in enumerate(mf4_files, start=1):
        percent = (idx / total_files) * 100
        print(f"[PROGRESS] {percent:.1f}% ({idx}/{total_files}) | {mf4_path.name}", end="\r", flush=True)

        # 🔥 Skip extremely small files (likely invalid)
        if mf4_path.stat().st_size < 512:
            print()
            print(f"[SKIP] {mf4_path.name}: too small")
            continue

        rel_path = mf4_path.relative_to(source_root).with_suffix(".csv")
        csv_path = output_root / rel_path

        should_convert = force or not csv_path.exists()

        if not should_convert:
            if not _is_csv_valid(csv_path):
                should_convert = True
            else:
                should_convert = mf4_path.stat().st_mtime > csv_path.stat().st_mtime

        if not should_convert:
            continue

        try:
            _convert_one_file(mf4_path, csv_path)
        except Exception as exc:
            print()
            print(f"[ERROR] {mf4_path.name} ({exc})")

    print()
    print("[DONE] MF4 conversion completed")


def main() -> None:
    run_mf4_conversion("train")


if __name__ == "__main__":
    main()