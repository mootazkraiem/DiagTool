from __future__ import annotations

import sys
from pathlib import Path

try:
    from backend.ml.steps.step7_hybrid_fusion import main
except ModuleNotFoundError:
    sys.path.append(str(Path(__file__).resolve().parents[3]))
    from backend.ml.steps.step7_hybrid_fusion import main


if __name__ == "__main__":
    main()
