from __future__ import annotations

import sys
from pathlib import Path

try:
    from backend.ml.training.train_residual_ml import main
except ModuleNotFoundError:
    sys.path.append(str(Path(__file__).resolve().parents[3]))
    from backend.ml.training.train_residual_ml import main


if __name__ == "__main__":
    main()
