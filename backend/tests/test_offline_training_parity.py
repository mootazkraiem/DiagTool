"""Offline scoring reproduces the transform the anomaly models were trained with.

backend.ml.state_based_pipeline.train() prepared every training source through
backend.ml.feature_engineering: rolling per-CAN-ID features, then
normalize_per_can_id - each feature z-scored with the mean and population
standard deviation of that identifier's rows in that source - then the saved
RobustScaler and IsolationForest. The statistics were not persisted.

Offline scoring used to feed the model the runtime feature vector instead: raw,
un-normalised values, and without two of the nine features the Skoda bundles
need, which were silently scored as 0.0. These tests hold the offline path to
training's definitions.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.ml import feature_engineering as training_fe  # noqa: E402
from backend.ml.runtime.vehicle_scoring import training_parity_features  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SKODA = ROOT / "assets" / "Skoda Enyaq" / "file_16.csv"
MODELS = ROOT / "assets" / "models"
BYTES = [f"b{i}" for i in range(8)]

SKODA_DRIVING_FEATURES = [
    "time_diff", "rolling_std_time_diff", "rolling_mean_byte_diff", "rolling_byte_diff_std",
    "rolling_max_byte_diff", "rolling_min_byte_diff", "rolling_range_byte_diff",
    "msg_frequency", "changed_bytes_count",
]


def _capture() -> pd.DataFrame:
    """Chronological, three identifiers interleaved, varied payloads and gaps."""
    rng = np.random.default_rng(7)
    rows = []
    t = 0.0
    for i in range(240):
        cid = (0x1A2, 0x7D1, 0x767)[i % 3]
        t += (0.010, 0.0005, 0.050)[i % 3] * (1 + 0.3 * rng.random())
        payload = [int(x) for x in rng.integers(0, 256, 8)] if cid != 0x767 else [i % 256, 0, 0, 0, 0, 0, 0, 0]
        rows.append((t, cid, *payload))
    return pd.DataFrame(rows, columns=["timestamp", "can_id", *BYTES])


def _independent(frames: pd.DataFrame) -> pd.DataFrame:
    """Training's features and normalisation, computed here without the helper."""
    grouped = frames.sort_values(["can_id", "timestamp"], kind="mergesort").reset_index(drop=True)
    feats = training_fe.build_features(grouped)
    out = feats.copy()
    out[training_fe.FEATURE_COLS] = out[training_fe.FEATURE_COLS].astype(float)
    for _, g in feats.groupby("can_id", sort=False):
        x = g[training_fe.FEATURE_COLS].to_numpy(dtype=np.float64)
        out.loc[g.index, training_fe.FEATURE_COLS] = (x - x.mean(axis=0)) / (x.std(axis=0, ddof=0) + 1e-6)
    return out


def _by_key(df: pd.DataFrame) -> pd.DataFrame:
    return df.sort_values(["can_id", "timestamp"], kind="mergesort").reset_index(drop=True)


# ── normalisation statistics ─────────────────────────────────────────────────

def test_statistics_come_from_the_complete_capture() -> None:
    frames = _capture()
    out = training_parity_features(frames)

    expected = _by_key(_independent(frames))
    got = _by_key(out)
    np.testing.assert_allclose(
        got[training_fe.FEATURE_COLS].to_numpy(dtype=float),
        expected[training_fe.FEATURE_COLS].to_numpy(dtype=float),
        atol=1e-9,
    )


def test_each_identifier_is_centred_on_its_own_capture_mean() -> None:
    out = training_parity_features(_capture())
    for cid, g in out.groupby("can_id"):
        for f in ("rolling_mean_byte_diff", "msg_frequency"):
            assert abs(float(g[f].mean())) < 1e-6, f"0x{cid:X} {f} not centred over the capture"


def test_population_standard_deviation_like_training() -> None:
    """ddof=0, exactly as normalize_per_can_id uses np.std."""
    frames = _capture()
    out = _by_key(training_parity_features(frames))
    raw = training_fe.build_features(frames.sort_values(["can_id", "timestamp"], kind="mergesort").reset_index(drop=True))

    g = raw[raw["can_id"] == 0x1A2]["rolling_mean_byte_diff"].to_numpy(dtype=float)
    pop = (g - g.mean()) / (g.std(ddof=0) + 1e-6)
    sample = (g - g.mean()) / (g.std(ddof=1) + 1e-6)

    got = out[out["can_id"] == 0x1A2]["rolling_mean_byte_diff"].to_numpy(dtype=float)
    np.testing.assert_allclose(got, pop, atol=1e-9)
    assert not np.allclose(got, sample, atol=1e-9)


def test_a_constant_feature_normalises_to_about_zero() -> None:
    rows = [(i * 0.1, 0x100, 5, 5, 5, 5, 5, 5, 5, 5) for i in range(40)]
    frames = pd.DataFrame(rows, columns=["timestamp", "can_id", *BYTES])
    out = training_parity_features(frames)
    # identical payloads: every byte-difference feature is constant
    for f in ("byte_diff", "rolling_mean_byte_diff", "rolling_min_byte_diff", "rolling_range_byte_diff"):
        assert np.abs(out[f].to_numpy(dtype=float)).max() < 1e-3, f


# ── feature coverage ─────────────────────────────────────────────────────────

def test_rolling_min_and_range_byte_diff_are_produced() -> None:
    out = training_parity_features(_capture())
    assert "rolling_min_byte_diff" in out.columns
    assert "rolling_range_byte_diff" in out.columns


def test_every_skoda_model_feature_is_produced() -> None:
    from backend.ml.runtime.realtime_engine import RealtimeEngine

    bundle = RealtimeEngine(vehicle_id="skoda_enyaq", score_ml=False).models.bundle_for("skoda_enyaq")
    assert bundle is not None
    out = training_parity_features(_capture())
    for state in ("driving", "idle"):
        required = bundle.required_features(state)
        assert required == SKODA_DRIVING_FEATURES
        assert set(required) <= set(out.columns), f"{state}: {set(required) - set(out.columns)} missing"


def test_a_missing_required_feature_fails_with_its_name() -> None:
    from backend.ml.runtime.realtime_engine import RealtimeEngine

    store = RealtimeEngine(vehicle_id="skoda_enyaq", score_ml=False).models
    out = training_parity_features(_capture()).drop(columns=["rolling_min_byte_diff"])

    with pytest.raises(ValueError, match="rolling_min_byte_diff"):
        store.score_feature_columns(["driving"] * len(out), out, vehicle="skoda_enyaq")


def test_frames_without_payload_are_rejected_not_zero_filled() -> None:
    frames = _capture().drop(columns=["b3"])
    with pytest.raises(ValueError, match="b3"):
        training_parity_features(frames)


# ── order ────────────────────────────────────────────────────────────────────

def test_output_is_in_the_callers_chronological_order() -> None:
    frames = _capture()
    out = training_parity_features(frames)
    assert len(out) == len(frames)
    np.testing.assert_array_equal(out["can_id"].to_numpy(), frames["can_id"].to_numpy())
    np.testing.assert_allclose(out["timestamp"].to_numpy(), frames["timestamp"].to_numpy())


# ── what must not have changed ───────────────────────────────────────────────

ARTIFACT_SHA256 = {
    "skoda_enyaq/model_driving.joblib": "02b6f4ed646145a395481cb7acda88c1ced624f6bd280fbbf2b8aec2670adb76",
    "skoda_enyaq/scaler_driving.joblib": "a46dbee19ebb7193ec6919ee1b6415dd2bbd453fea788fbefa99082169646c42",
    "skoda_enyaq/thresholds.json": "fdc9e7daf5986aba53b0fde5fad84545263c147b8d23b8f5bf077e47cc4382ff",
    "skoda_enyaq/feature_sets.json": "613ee25befcc987f382febfefa6aeb1b058b8626eb605eafb6dc95e039e40b84",
}


@pytest.mark.parametrize("name", sorted(ARTIFACT_SHA256))
def test_model_artifacts_are_unchanged(name: str) -> None:
    digest = hashlib.sha256((MODELS / name).read_bytes()).hexdigest()
    assert digest == ARTIFACT_SHA256[name]


def test_live_engine_does_not_use_the_offline_path(monkeypatch) -> None:
    """Realtime scoring still goes through RuntimeModelStore.score, untouched."""
    from backend.ml.runtime import model_loader
    from backend.ml.runtime.realtime_engine import CanFrame, RealtimeEngine

    def _forbidden(*_a, **_k):
        raise AssertionError("live scoring reached the offline parity path")

    monkeypatch.setattr(model_loader.RuntimeModelStore, "score_feature_columns", _forbidden)
    monkeypatch.setattr(model_loader.StateModelBundle, "score_feature_columns", _forbidden)

    engine = RealtimeEngine(vehicle_id="skoda_enyaq", score_ml=True)
    frames = _capture()
    for ts, cid, *bs in frames[["timestamp", "can_id", *BYTES]].to_numpy():
        out = engine.process_frame(CanFrame(timestamp=float(ts), can_id=int(cid), payload=tuple(int(b) for b in bs)))
        assert 0.0 <= float(out["ml_norm"]) <= 2.0


@pytest.mark.skipif(not SKODA.exists(), reason="Skoda recording not present")
def test_reference_recording_has_all_features_and_keeps_every_frame() -> None:
    from backend.data_processing.feature_engineering import FeatureEngineer
    from backend.offline.session_analyzer import _load_csv

    frames = list(_load_csv(SKODA))
    raw = pd.DataFrame([(t, c, *p) for t, c, p in frames], columns=["timestamp", "can_id", *BYTES])
    featured = FeatureEngineer.build(raw)

    out = training_parity_features(featured)

    assert len(out) == 19339
    assert set(SKODA_DRIVING_FEATURES) <= set(out.columns)
    np.testing.assert_allclose(out["timestamp"].to_numpy(), featured["timestamp"].to_numpy())
