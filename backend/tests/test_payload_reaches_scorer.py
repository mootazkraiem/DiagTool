"""The frame's own payload must reach the ML scorer.

add_features() returned only timestamp, can_id and the engineered columns, so
b0..b7 were gone by the time score_frames() saw the frame. score_frames falls
back to an all-zero payload when those columns are missing, which meant
/analyze scored every frame of every recording as though its eight data bytes
were zero.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.data_processing.feature_engineering import FeatureEngineer  # noqa: E402
from backend.ml.core.feature_engineering import add_features  # noqa: E402
from backend.ml.runtime.vehicle_scoring import _BYTE_COLS  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SKODA = ROOT / "assets" / "Skoda Enyaq" / "file_16.csv"


def _frame(rows: list[tuple]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["timestamp", "can_id", *_BYTE_COLS])


SAMPLE = _frame([
    (0.000, 0x1A2, 3, 34, 70, 91, 85, 85, 85, 85),
    (0.010, 0x1A2, 5, 98, 70, 91, 2, 22, 170, 170),
    (0.020, 0x7D1, 16, 19, 98, 30, 50, 0, 115, 46),
    (0.030, 0x7D1, 33, 55, 255, 141, 246, 143, 2, 162),
    (0.040, 0x767, 48, 0, 0, 0, 0, 0, 0, 0),
])


# ── 1. the payload survives feature engineering ──────────────────────────────

def test_byte_columns_survive_add_features() -> None:
    out = add_features(SAMPLE)
    assert [c for c in _BYTE_COLS if c in out.columns] == _BYTE_COLS


def test_engineered_columns_are_still_produced() -> None:
    """Carrying the payload must not cost the engineered features."""
    out = add_features(SAMPLE)
    for column in ("time_diff", "msg_frequency", "payload_entropy", "can_id_entropy"):
        assert column in out.columns


def test_payload_values_are_unchanged_not_reconstructed() -> None:
    """The same eight bytes come out, frame for frame (order aside)."""
    out = add_features(SAMPLE)

    def rows(df):
        return sorted(tuple(r) for r in df[["timestamp", "can_id", *_BYTE_COLS]].to_numpy().tolist())

    assert rows(out) == rows(SAMPLE)


def test_every_row_keeps_its_own_payload() -> None:
    """The guard against the subtle version of this bug.

    build_features sorts by (can_id, timestamp), so the output is not in input
    order. Each row must still carry the bytes of the frame it describes -
    re-attaching the payload by position after the sort would hand a frame
    another frame's data, which is worse than dropping it.
    """
    out = add_features(SAMPLE)
    assert len(out) == len(SAMPLE)

    source = {(row.timestamp, row.can_id): [getattr(row, c) for c in _BYTE_COLS]
              for row in SAMPLE.itertuples(index=False)}

    for row in out.itertuples(index=False):
        expected = source[(row.timestamp, row.can_id)]
        assert [getattr(row, c) for c in _BYTE_COLS] == expected, (
            f"frame at t={row.timestamp} id=0x{int(row.can_id):X} carries the wrong payload"
        )


def test_payload_survives_the_internal_regrouping() -> None:
    """The bytes have to survive a sort they are not sorted by.

    build_features groups by (can_id, timestamp) internally and add_features
    restores chronological order afterwards, so each frame's bytes make two
    moves before they are scored.
    """
    from backend.ml.core.feature_engineering import build_features

    grouped = build_features(SAMPLE, keep_payload=True)
    assert list(zip(grouped["can_id"], grouped["timestamp"])) == sorted(
        zip(grouped["can_id"], grouped["timestamp"])
    )

    source = {(r.timestamp, r.can_id): [getattr(r, c) for c in _BYTE_COLS]
              for r in SAMPLE.itertuples(index=False)}
    for row in grouped.itertuples(index=False):
        assert [getattr(row, c) for c in _BYTE_COLS] == source[(row.timestamp, row.can_id)]


def test_input_without_payload_columns_is_rejected() -> None:
    """Pre-existing behaviour: the features cannot be built without the bytes."""
    bare = pd.DataFrame({"timestamp": [0.0, 0.01, 0.02], "can_id": [1, 1, 2]})
    with pytest.raises(ValueError, match="missing required columns"):
        add_features(bare)


# ── 2/3. a real recording reaches the scorer with its real bytes ─────────────

@pytest.mark.skipif(not SKODA.exists(), reason="Skoda recording not present")
def test_real_recording_payload_reaches_the_scoring_frame() -> None:
    from backend.offline.session_analyzer import _load_csv

    frames = list(_load_csv(SKODA))
    raw = _frame([(ts, cid, *payload) for ts, cid, payload in frames])

    featured = FeatureEngineer.build(raw)

    assert [c for c in _BYTE_COLS if c in featured.columns] == _BYTE_COLS
    assert len(featured) == len(raw) == 19339

    # Every scored frame carries the bytes of the frame it describes. Compared
    # per frame because build_features sorts by (can_id, timestamp).
    cols = ["timestamp", "can_id", *_BYTE_COLS]
    assert (sorted(tuple(r) for r in featured[cols].to_numpy().tolist())
            == sorted(tuple(r) for r in raw[cols].to_numpy().tolist()))

    # the recording's first frame, byte for byte, wherever it now sits
    first = featured[(featured["timestamp"] == 0.0) & (featured["can_id"] == 0x17FC00B9)]
    assert first.iloc[0][_BYTE_COLS].tolist() == [3, 34, 70, 91, 85, 85, 85, 85]


# ── 4. the scorer no longer sees an all-zero payload ────────────────────────

@pytest.mark.skipif(not SKODA.exists(), reason="Skoda recording not present")
def test_scorer_does_not_receive_all_zero_payloads() -> None:
    from backend.offline.session_analyzer import _load_csv

    frames = list(_load_csv(SKODA))
    raw = _frame([(ts, cid, *payload) for ts, cid, payload in frames])
    featured = FeatureEngineer.build(raw)

    payload_cols = [c for c in _BYTE_COLS if c in featured.columns]
    assert payload_cols, "score_frames falls back to zeros when these are absent"

    zero_rows = int((featured[payload_cols].sum(axis=1) == 0).sum())
    source_zero_rows = int((raw[payload_cols].sum(axis=1) == 0).sum())
    assert zero_rows == source_zero_rows, (
        "frames scored with an all-zero payload must only be frames that really "
        "carried all-zero bytes"
    )


# ── ordering: the scorer must receive chronological frames ───────────────────
#
# build_features groups by (can_id, timestamp) for its rolling per-identifier
# columns. Those values are finished by the time add_features returns, and what
# consumes the frame next walks it through a stateful engine whose
# can_id_entropy is the entropy of the last 200 identifiers seen. Grouped, that
# window holds one identifier, entropy collapses, and the state classifier
# answers "parking" for traffic recorded while driving.

INTERLEAVED = _frame([
    (0.000, 0x1A2, 1, 0, 0, 0, 0, 0, 0, 0),
    (0.001, 0x7D1, 2, 0, 0, 0, 0, 0, 0, 0),
    (0.002, 0x767, 3, 0, 0, 0, 0, 0, 0, 0),
    (0.003, 0x1A2, 4, 0, 0, 0, 0, 0, 0, 0),
    (0.004, 0x7D1, 5, 0, 0, 0, 0, 0, 0, 0),
    (0.005, 0x767, 6, 0, 0, 0, 0, 0, 0, 0),
    (0.006, 0x1A2, 7, 0, 0, 0, 0, 0, 0, 0),
    (0.007, 0x7D1, 8, 0, 0, 0, 0, 0, 0, 0),
])


def test_input_frames_are_chronological() -> None:
    """Precondition: a capture is recorded in time order."""
    assert INTERLEAVED["timestamp"].tolist() == sorted(INTERLEAVED["timestamp"].tolist())


def test_feature_engineering_still_groups_per_can_id_internally() -> None:
    """The rolling per-identifier columns are still produced."""
    from backend.ml.core.feature_engineering import build_features

    grouped = build_features(INTERLEAVED)
    pairs = list(zip(grouped["can_id"], grouped["timestamp"]))
    assert pairs == sorted(pairs), "build_features keeps its (can_id, timestamp) grouping"
    assert "rolling_std_time_diff" in grouped.columns


def test_add_features_returns_chronological_order() -> None:
    out = add_features(INTERLEAVED)
    assert out["timestamp"].tolist() == sorted(out["timestamp"].tolist())


def test_scorer_does_not_receive_can_id_grouped_order() -> None:
    """The specific bad ordering must not come back."""
    out = add_features(INTERLEAVED)
    pairs = list(zip(out["can_id"], out["timestamp"]))
    assert pairs != sorted(pairs), "frames must not be grouped by identifier for the scorer"
    assert out["can_id"].tolist() == INTERLEAVED["can_id"].tolist()


@pytest.mark.skipif(not SKODA.exists(), reason="Skoda recording not present")
def test_real_recording_reaches_the_scorer_whole_and_in_order() -> None:
    """End to end up to the models: every frame, chronological, payload intact.

    Routing and scoring are not asserted here: the shipped Skoda bundle has no
    manifest and is refused (test_model_manifest.py).
    """
    from backend.ml.runtime.vehicle_scoring import training_parity_features
    from backend.offline.session_analyzer import _load_csv

    frames = list(_load_csv(SKODA))
    raw = _frame([(ts, cid, *payload) for ts, cid, payload in frames])
    featured = FeatureEngineer.build(raw)

    assert len(featured) == len(frames)
    assert featured["timestamp"].tolist() == sorted(featured["timestamp"].tolist())
    assert all(f"b{i}" in featured.columns for i in range(8))

    parity = training_parity_features(featured)
    assert len(parity) == len(featured)
    assert parity["timestamp"].tolist() == featured["timestamp"].tolist()
    assert parity["can_id"].tolist() == featured["can_id"].tolist()
