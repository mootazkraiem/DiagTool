from __future__ import annotations

from pathlib import Path

import pandas as pd


def export_log(rows: list[dict], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out, index=False)
