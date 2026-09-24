"""Batch scoring computes can_id_entropy the way training defined it.

Training (backend.ml.core.feature_engineering.build_features) computes one
entropy value per dataset, so every training row carried the same number. The
live engine cannot do that on a stream and estimates it from a rolling window of
the last 200 identifiers, reporting 0.0 until it has seen ten. The state
classifier consumes this feature, so those opening frames were read as
"parking", and a vehicle with no parking model left them unscored.

Batch scoring has the whole capture before it starts, so it uses the training
definition. The live estimator is deliberately untouched.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.ml.runtime.vehicle_scoring import global_can_id_entropy  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SKODA = ROOT / "assets" / "Skoda Enyaq" / "file_16.csv"
BYTES = [f"b{i}" for i in range(8)]

# The value build_features produces for this recording.
SKODA_GLOBAL_ENTROPY = 2.0767973425529616


def _load_skoda() -> pd.DataFrame:
    from backend.offline.session_analyzer import _load_csv

    frames = list(_load_csv(SKODA))
    return pd.DataFrame([(t, c, *p) for t, c, p in frames],
                        columns=["timestamp", "can_id", *BYTES])


# ── the formula matches training ─────────────────────────────────────────────

def test_matches_the_training_formula() -> None:
    """Same expression as build_features, checked independently."""
    ids = pd.Series([1, 1, 1, 2, 2, 3])
    freq = ids.value_counts(normalize=True)
    expected = float(-(freq * np.log(freq + 1e-12)).sum())
    assert global_can_id_entropy(ids) == pytest.approx(expected)


def test_uniform_distribution_is_log_n() -> None:
    assert global_can_id_entropy(pd.Series([1, 2, 3, 4])) == pytest.approx(np.log(4), abs=1e-9)


def test_single_identifier_has_no_entropy() -> None:
    assert global_can_id_entropy(pd.Series([7] * 50)) == pytest.approx(0.0, abs=1e-9)


def test_empty_capture_is_zero_not_an_error() -> None:
    assert global_can_id_entropy(pd.Series([], dtype=int)) == 0.0


@pytest.mark.skipif(not SKODA.exists(), reason="Skoda recording not present")
def test_reference_recording_global_value() -> None:
    raw = _load_skoda()
    assert global_can_id_entropy(raw["can_id"]) == pytest.approx(SKODA_GLOBAL_ENTROPY, abs=1e-9)


# ── batch scoring: no warm-up, nothing lost to entropy ───────────────────────

@pytest.mark.skipif(not SKODA.exists(), reason="Skoda recording not present")
def test_offline_capture_never_starts_at_zero_entropy() -> None:
    """Every frame is scored against the same whole-capture value."""
    from backend.data_processing.feature_engineering import FeatureEngineer

    featured = FeatureEngineer.build(_load_skoda())
    value = global_can_id_entropy(featured["can_id"])

    assert value > 1.0, "a ten-identifier capture has real entropy"
    # One value for the whole file means there is no opening window to warm up.
    assert global_can_id_entropy(featured["can_id"].head(20)) >= 0.0


@pytest.mark.skipif(not SKODA.exists(), reason="Skoda recording not present")
def test_offline_runtime_vectors_carry_the_whole_capture_entropy() -> None:
    """Every frame's classifier input carries the global value - no warm-up zeros.

    (Scoring end to end is refused for the shipped, unmanifested bundles; see
    test_model_manifest.py. This checks the input the classifier would get.)
    """
    from backend.data_processing.feature_engineering import FeatureEngineer
    from backend.ml.runtime.runtime_config import VALIDATION_CONFIG
    from backend.ml.runtime.vehicle_scoring import _runtime_feature_vectors

    featured = FeatureEngineer.build(_load_skoda())
    vectors = _runtime_feature_vectors(featured, "skoda_enyaq", VALIDATION_CONFIG)

    assert len(vectors) == 19339
    # compute_model_features clips and log1p-transforms, as build_features does.
    expected = float(np.log1p(SKODA_GLOBAL_ENTROPY))
    assert all(abs(v["can_id_entropy"] - expected) < 1e-9 for v in vectors)


# ── the live estimator is untouched ──────────────────────────────────────────

def test_live_engine_still_uses_the_rolling_window() -> None:
    """A stream has no whole capture, so the windowed estimator stays."""
    from backend.ml.runtime.realtime_engine import CanFrame, RealtimeEngine

    engine = RealtimeEngine(vehicle_id="", score_ml=False)
    assert engine._recent_can_ids.maxlen == 200

    seen = []
    for i in range(60):
        out = engine.process_frame(
            CanFrame(timestamp=i * 0.01, can_id=0x100 + (i % 12), payload=(1, 2, 3, 4, 5, 6, 7, 8))
        )
        seen.append(float(out["can_id_entropy"]))

    assert seen[0] == 0.0, "the rolling estimator still warms up"
    assert max(seen) > 1.0, "and still rises once the window fills"


# ── the anomaly models still do not use this feature ─────────────────────────

def test_can_id_entropy_absent_from_every_anomaly_model_bundle() -> None:
    """It is dropped at training by variance thresholding; nothing re-adds it."""
    bundles = sorted((ROOT / "assets" / "models").glob("*/feature_sets.json"))
    assert bundles, "no model bundles found"

    for path in bundles:
        sets = json.loads(path.read_text())
        for state, feats in sets.items():
            assert "can_id_entropy" not in feats, f"{path.parent.name}/{state} now uses it"
