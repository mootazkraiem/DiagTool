from __future__ import annotations

import sys
from pathlib import Path

try:
    from backend.ml.evaluation.evaluate_ml_baseline import main
except ModuleNotFoundError:
    sys.path.append(str(Path(__file__).resolve().parents[3]))
    from backend.ml.evaluation.evaluate_ml_baseline import main


if __name__ == "__main__":
    main()
