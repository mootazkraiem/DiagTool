"""Canonical features: one definition for training, offline analysis and live.

Batch and live must agree exactly, features must be causal (nothing learned
from the capture being scored), and nothing a live stream cannot compute may
appear in the feature set.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
import pandas as pd
import pytest

from backend.ml.features import canonical
from backend.ml.features.canonical import FEATURES, WINDOW, CanonicalFeatureStream, compute_features


def _frames(n: int = 1500, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ids = rng.choice([0x100, 0x1A0, 0x2F0, 0x3C4, 0x7E8], n)
    df = pd.DataFrame({"timestamp": np.cumsum(rng.uniform(0.0002, 0.004, n)), "can_id": ids})
    for i in range(8):
        df[f"b{i}"] = rng.integers(0, 256, n)
    return df


def test_batch_equals_the_stream_exactly() -> None:
    df = _frames()
    x, ready = canonical.compute_features_frame(df)
    stream = CanonicalFeatureStream()
    for i, row in enumerate(df.itertuples(index=False)):
        vec = stream.update(row.timestamp, row.can_id, [getattr(row, f"b{k}") for k in range(8)])
        assert (vec is None) == (not ready[i])
        if vec is not None:
            assert vec == x[i].tolist()          # bit-identical, not approximately equal


def test_deterministic() -> None:
    df = _frames()
    a, ra = canonical.compute_features_frame(df)
    b, rb = canonical.compute_features_frame(df)
    assert np.array_equal(ra, rb) and np.array_equal(a[ra], b[rb])


def test_warm_up_is_explicit_not_zero_filled() -> None:
    df = pd.DataFrame({"timestamp": [i * 0.01 for i in range(WINDOW + 3)], "can_id": [0x100] * (WINDOW + 3),
                       **{f"b{i}": [0] * (WINDOW + 3) for i in range(8)}})
    x, ready = canonical.compute_features_frame(df)
    assert not ready[:WINDOW].any()
    assert ready[WINDOW:].all()
    assert np.isnan(x[:WINDOW]).all()


def test_features_are_causal_no_statistic_from_the_capture() -> None:
    """Appending later traffic must not change any earlier frame's features."""
    df = _frames(2000)
    head, _ = canonical.compute_features_frame(df.iloc[:1000])
    full, _ = canonical.compute_features_frame(df)
    assert np.array_equal(np.nan_to_num(head, nan=-1), np.nan_to_num(full[:1000], nan=-1))


def test_byte_difference_does_not_wrap() -> None:
    stream = CanonicalFeatureStream()
    vec = None
    for i in range(WINDOW + 1):
        payload = (1 + (i % 2), 0, 0, 0, 0, 0, 0, 0)          # 1,2,1,2,... : |diff| = 1 in one byte
        vec = stream.update(i * 0.01, 0x100, payload)
    assert vec[FEATURES.index("byte_diff")] == pytest.approx(math.log1p(1 / 8))
    assert vec[FEATURES.index("rolling_max_byte_diff")] == pytest.approx(math.log1p(1 / 8))


def test_live_payload_delta_no_longer_wraps() -> None:
    from backend.ml.runtime.feature_updates import update_payload
    from backend.ml.runtime.state_manager import StateManager

    st = StateManager(50, 50, 50, 50).get(0x100)
    update_payload(st, (1, 0, 0, 0, 0, 0, 0, 0))
    out = update_payload(st, (2, 0, 0, 0, 0, 0, 0, 0))
    assert out["payload_delta"] == pytest.approx(0.125)       # uint8 arithmetic gave 31.875


def test_short_payloads_are_padded_identically() -> None:
    a = CanonicalFeatureStream()
    b = CanonicalFeatureStream()
    for i in range(WINDOW + 1):
        va = a.update(i * 0.01, 1, (5, 6))
        vb = b.update(i * 0.01, 1, (5, 6, 0, 0, 0, 0, 0, 0))
    assert va == vb


def test_only_runtime_computable_features() -> None:
    assert "rolling_min_byte_diff" not in FEATURES
    assert "rolling_range_byte_diff" not in FEATURES
    assert len(FEATURES) == len(set(FEATURES)) == 9
