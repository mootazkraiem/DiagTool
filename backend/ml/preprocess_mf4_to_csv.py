from __future__ import annotations

import logging
import time
from pathlib import Path

from asammdf import MDF


logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger("preprocess_mf4_to_csv")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = PROJECT_ROOT / "assets" / "log_files"
OUTPUT_ROOT = PROJECT_ROOT / "assets" / "processed_csv"
MAX_ROWS_PER_FILE = 50_000
MAX_FILES = None


def discover_files(source_root: Path = SOURCE_ROOT, max_files: int | None = MAX_FILES) -> list[Path]:
    """
    Step 0 intentionally separates MF4 parsing from ML training.
    This keeps the training pipeline fast by converting heavy MF4 files once.
    """
    mf4_upper = list(source_root.rglob("*.MF4"))
    mf4_lower = list(source_root.rglob("*.mf4"))
    files = sorted(set(mf4_upper + mf4_lower), key=lambda p: str(p))
    if max_files is not None:
        files = files[:max_files]
    logger.info(f"Total MF4 files found: {len(files)}")
    return files


def convert_mf4_to_csv(files: list[Path], output_root: Path = OUTPUT_ROOT) -> None:
    start = time.perf_counter()
    output_root.mkdir(parents=True, exist_ok=True)
    total = len(files)
    if not files:
        logger.warning("No MF4 files found.")
        return

    saved = 0
    skipped = 0
    for idx, file_path in enumerate(files, start=1):
        logger.info(f"Processing file {idx} / {total}: {file_path}")
        try:
            mdf = MDF(str(file_path))
            df = mdf.to_dataframe()
            if df.empty:
                skipped += 1
                logger.warning(f"Skipped file: {file_path} | reason: empty dataframe")
                continue
            df = df.head(MAX_ROWS_PER_FILE)
            out_path = output_root / f"file_{idx - 1}.csv"
            df.to_csv(out_path, index=True)
            saved += 1
            logger.info(f"Rows saved: {len(df):,}")
        except Exception as exc:
            skipped += 1
            logger.warning(f"Skipped file: {file_path} | reason: {exc}")

    elapsed = time.perf_counter() - start
    logger.info(f"Done. Saved: {saved}, Skipped: {skipped}, Time: {elapsed:.2f}s")


def main() -> None:
    files = discover_files(SOURCE_ROOT, MAX_FILES)
    convert_mf4_to_csv(files, OUTPUT_ROOT)


if __name__ == "__main__":
    main()
