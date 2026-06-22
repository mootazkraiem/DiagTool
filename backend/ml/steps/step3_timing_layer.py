from __future__ import annotations

import sys
from pathlib import Path

try:
    from backend.ml.graphing.generate_timing_graphs import main
except ModuleNotFoundError:
    sys.path.append(str(Path(__file__).resolve().parents[3]))
    from backend.ml.graphing.generate_timing_graphs import main


if __name__ == "__main__":
    main()
