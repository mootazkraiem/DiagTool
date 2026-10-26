"""Temporal pattern labels (backend/ml/temporal.py): a DoS burst needs volume."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd

from backend.ml.temporal import DOS_MIN_FREQ_HZ, detect_patterns


def _frame(can_id: int, freq: float) -> pd.DataFrame:
    return pd.DataFrame({"can_id": [can_id], "timestamp": [1.0], "msg_frequency": [freq]})


def test_a_near_silent_identifier_at_a_low_rate_is_not_a_dos_burst():
    # Baseline just above 0: 0.2 msg/s is "5x the baseline" but no flood (Jaguar 0x063).
    out = detect_patterns(_frame(0x063, 0.2), {"0x063": 0.01})
    assert out["temporal_pattern"].iloc[0] == "normal"


def test_a_real_flood_is_still_a_dos_burst():
    out = detect_patterns(_frame(0x100, 400.0), {"0x100": 10.0})
    assert out["temporal_pattern"].iloc[0] == "dos_burst"


def test_the_floor_itself():
    below = detect_patterns(_frame(0x100, DOS_MIN_FREQ_HZ - 1), {"0x100": 1.0})
    at = detect_patterns(_frame(0x100, DOS_MIN_FREQ_HZ), {"0x100": 1.0})
    assert below["temporal_pattern"].iloc[0] == "normal"
    assert at["temporal_pattern"].iloc[0] == "dos_burst"
