from __future__ import annotations

import sys
from pathlib import Path

try:
    from backend.progress import print_progress
    from backend.ml.state_based_pipeline import train as train_state_models
except ModuleNotFoundError:
    sys.path.append(str(Path(__file__).resolve().parents[2]))
    from backend.progress import print_progress
    from backend.ml.state_based_pipeline import train as train_state_models


def main() -> None:
    # Unified entrypoint:
    # MF4 -> CSV -> Feature Engineering -> State Detection -> State Models
    train_state_models()
    print("[INFO] training pipeline completed")


if __name__ == "__main__":
    main()
