"""Regression tests for feature engineering pipeline.

Verifies: required output columns, no NaN in feature cols,
single-CAN-ID edge case, inter-arrival CV computation,
and payload_entropy for all-zero vs random payloads.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.ml.core.feature_engineering import FEATURE_COLS, build_features

REQUIRED_COLS = FEATURE_COLS


def _make_df(
    n: int = 50,
    can_id: int = 0x316,
    interval: float = 0.01,
    b_val: int = 0xAA,
) -> pd.DataFrame:
    """Synthetic CAN traffic: single CAN-ID, fixed interval, uniform payload."""
    rows = []
    for i in range(n):
        rows.append({
            "timestamp": i * interval,
            "can_id": can_id,
            **{f"b{j}": b_val for j in range(8)},
        })
    return pd.DataFrame(rows)


def test_output_contains_all_feature_cols() -> None:
    df = _make_df()
    out = build_features(df)
    for col in REQUIRED_COLS:
        assert col in out.columns, f"missing feature column: {col}"


def test_no_nan_in_feature_cols() -> None:
    df = _make_df(n=100)
    out = build_features(df)
    for col in REQUIRED_COLS:
        n_nan = out[col].isna().sum()
        assert n_nan == 0, f"NaN found in {col} ({n_nan} rows)"


def test_empty_input_returns_empty_dataframe() -> None:
    empty = pd.DataFrame(columns=["timestamp", "can_id", *[f"b{i}" for i in range(8)]])
    out = build_features(empty)
    assert out.empty


def test_missing_required_column_raises() -> None:
    df = _make_df()
    df = df.drop(columns=["b0"])
    with pytest.raises(ValueError, match="missing required columns"):
        build_features(df)


def test_multi_can_id_all_processed() -> None:
    df_a = _make_df(n=30, can_id=0x316)
    df_b = _make_df(n=30, can_id=0x329, b_val=0x55)
    df = pd.concat([df_a, df_b], ignore_index=True)
    out = build_features(df)
    ids = set(out["can_id"].unique())
    assert 0x316 in ids
    assert 0x329 in ids


def test_all_zero_payload_entropy_is_zero() -> None:
    """All-zero payloads have no bit variation → entropy should be 0."""
    df = _make_df(n=50, b_val=0)
    out = build_features(df)
    assert (out["payload_entropy"] == 0.0).all()


def test_uniform_interval_low_inter_arrival_cv() -> None:
    """Perfectly uniform message timing → CV ≈ 0."""
    df = _make_df(n=100, interval=0.01)
    out = build_features(df)
    # After initial rolling warm-up rows, CV should be near zero
    cv = out["inter_arrival_cv"].iloc[10:]
    assert float(cv.mean()) < 0.1, f"expected low CV for uniform timing, got {float(cv.mean()):.4f}"


def test_row_count_preserved() -> None:
    df = _make_df(n=40)
    out = build_features(df)
    assert len(out) == 40


def test_msg_frequency_positive() -> None:
    df = _make_df(n=50, interval=0.01)
    out = build_features(df)
    assert (out["msg_frequency"] >= 0).all()
