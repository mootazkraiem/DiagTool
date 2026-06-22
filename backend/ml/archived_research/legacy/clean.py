from __future__ import annotations

import shutil
from pathlib import Path


# clean.py lives at backend/ml/legacy/clean.py; project root is 3 levels up.
PROJECT_ROOT = Path(__file__).resolve().parents[3]
ASSETS_ROOT = PROJECT_ROOT / "assets"
OUTPUTS_ROOT = PROJECT_ROOT / "outputs"

# ML-generated outputs only
TARGET_DIRS = [
    ASSETS_ROOT / "train_csv",
    ASSETS_ROOT / "validation_csv",
    ASSETS_ROOT / "test_csv",
    ASSETS_ROOT / "clean_traincsv",
    ASSETS_ROOT / "processed_features",
    ASSETS_ROOT / "models",
    ASSETS_ROOT / "evaluation",
    OUTPUTS_ROOT / "pca",
]


def _is_safe_target(path: Path) -> bool:
    try:
        path.resolve().relative_to(ASSETS_ROOT.resolve())
        return True
    except Exception:
        pass
    try:
        path.resolve().relative_to(OUTPUTS_ROOT.resolve())
        return True
    except Exception:
        return False


def _remove_dir(path: Path) -> bool:
    if not path.exists():
        return False
    if not _is_safe_target(path):
        raise ValueError(f"unsafe delete target: {path}")
    shutil.rmtree(path)
    return True


def main() -> None:
    removed = 0
    for path in TARGET_DIRS:
        try:
            if _remove_dir(path):
                removed += 1
                print(f"[INFO] removed: {path}")
        except Exception as exc:
            print(f"[ERROR] failed to remove {path} ({exc})")

    print(f"[INFO] clean complete: {removed}/{len(TARGET_DIRS)} folders removed")


if __name__ == "__main__":
    main()
