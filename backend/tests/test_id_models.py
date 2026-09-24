"""Per-CAN-ID models (manifest schema 3): isolation between identifiers, sparse and
unseen identifiers, deterministic fitting, and the threshold calibration.

Built from small synthetic feature matrices; no real recording or model file is used.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
import pytest

from backend.ml.features import canonical
from backend.ml.runtime.model_manifest import (
    SCORED,
    SPARSE_ID,
    UNMODELLED_ID,
    UNSEEN_ID,
    IdModel,
    IdModelFamily,
    calibrate_threshold,
    normalised_score,
)
from backend.ml.training import clean_pipeline as cp

F = len(canonical.FEATURES)


def _rows(n: int, centre: float, seed: int) -> np.ndarray:
    return np.random.default_rng(seed).normal(centre, 1.0, size=(n, F))


def _fit(parts: dict[int, np.ndarray]) -> tuple[IdModelFamily, dict, dict, dict]:
    x = np.vstack(list(parts.values()))
    ids = np.concatenate([np.full(len(v), k) for k, v in parts.items()])
    models, id_models, sparse, unmodelled = cp.fit_id_models(x, ids, np.zeros(len(ids), dtype=int))
    fam = IdModelFamily(
        "t", {}, {int(k, 16): IdModel(e["features"], [canonical.FEATURES.index(f) for f in e["features"]],
                                      models[k], e["threshold"], e["median"]) for k, e in id_models.items()},
        {int(k, 16) for k in sparse}, {int(k, 16) for k in unmodelled})
    return fam, id_models, sparse, unmodelled


# ── calibration ──────────────────────────────────────────────────────────────

def test_calibration_flags_at_most_the_target_share() -> None:
    raw = np.random.default_rng(0).normal(size=5000)
    cal = calibrate_threshold(raw, 0.02)
    assert cal["k"] == 100 and cal["flagged_count"] == 100
    assert cal["threshold"] == np.sort(raw)[100]
    assert (raw < cal["threshold"]).sum() == cal["flagged_count"] <= math.floor(0.02 * len(raw))


def test_ties_at_the_threshold_are_not_flagged() -> None:
    raw = np.r_[np.full(10, -5.0), np.full(90, -1.0), np.linspace(0, 1, 900)]
    cal = calibrate_threshold(raw, 0.02)                  # k = 20: the 21st smallest is -1.0, tied 90 times
    assert cal["threshold"] == -1.0
    assert cal["flagged_count"] == 10                     # only the strictly lower rows
    assert cal["ties_at_threshold"] == 90


def test_calibration_rejects_non_finite_scores() -> None:
    with pytest.raises(ValueError):
        calibrate_threshold(np.array([0.1, np.nan, 0.3]), 0.02)


def test_normalised_score_anchors() -> None:
    s = normalised_score(np.array([-0.2, -0.5, -0.8, -2.0]), threshold=-0.5, median=-0.2)
    assert s.tolist() == [0.0, 0.5, 1.0, 1.0]


def test_training_rate_per_id_never_exceeds_target() -> None:
    fam, id_models, _, _ = _fit({0x10: _rows(3000, 0, 1), 0x20: _rows(1500, 5, 2)})
    for e in id_models.values():
        assert e["flagged_count"] <= math.floor(cp.TARGET_CONTAMINATION * e["rows"])


# ── identifier isolation ─────────────────────────────────────────────────────

def test_a_frame_is_judged_only_by_its_own_identifier() -> None:
    """Rows normal for 0x20 are far outside 0x10's normal: routed by ID, they are not flagged."""
    fam, *_ = _fit({0x10: _rows(3000, 0.0, 1), 0x20: _rows(3000, 8.0, 2)})
    probe = _rows(400, 8.0, 3)
    _, flag_own, _ = fam.score_rows(probe, np.full(400, 0x20))
    _, flag_other, _ = fam.score_rows(probe, np.full(400, 0x10))
    assert flag_own.mean() < 0.1
    assert flag_other.mean() > 0.9


def test_a_dominant_identifier_does_not_swamp_a_smaller_one() -> None:
    """The clean-1 failure: a small ID's normal rows flagged because a big ID dominates."""
    fam, id_models, _, _ = _fit({0x9: _rows(20000, 0.0, 1), 0x1: _rows(1200, 6.0, 2)})
    _, flagged, _ = fam.score_rows(_rows(500, 6.0, 4), np.full(500, 0x1))
    assert flagged.mean() < 0.1


def test_mixed_batch_equals_per_identifier_scoring() -> None:
    fam, *_ = _fit({0x10: _rows(2000, 0, 1), 0x20: _rows(2000, 3, 2)})
    a, b = _rows(50, 0, 5), _rows(50, 3, 6)
    mixed, _, _ = fam.score_rows(np.vstack([a, b]), np.r_[np.full(50, 0x10), np.full(50, 0x20)])
    sa, _, _ = fam.score_rows(a, np.full(50, 0x10))
    sb, _, _ = fam.score_rows(b, np.full(50, 0x20))
    assert np.array_equal(mixed, np.r_[sa, sb])


# ── sparse, unmodelled, unseen ───────────────────────────────────────────────

def test_sparse_identifier_is_reported_not_scored() -> None:
    fam, _, sparse, _ = _fit({0x10: _rows(2000, 0, 1), 0x7EC: _rows(cp.MIN_ID_ROWS - 1, 0, 2)})
    assert sparse == {"0x7EC": {"rows": cp.MIN_ID_ROWS - 1, "recordings": 1}}
    norm, flagged, status = fam.score_rows(_rows(5, 0, 3), np.full(5, 0x7EC))
    assert (status == SPARSE_ID).all() and np.isnan(norm).all() and not flagged.any()


def test_unseen_identifier_is_reported_not_scored_or_borrowed() -> None:
    fam, *_ = _fit({0x10: _rows(2000, 0, 1)})
    norm, flagged, status = fam.score_rows(_rows(5, 0, 3), np.full(5, 0x555))
    assert (status == UNSEEN_ID).all() and np.isnan(norm).all() and not flagged.any()
    assert fam.score_one(_rows(1, 0, 4)[0], 0x555) == (None, None, UNSEEN_ID)


def test_identifier_with_no_varying_feature_is_unmodelled() -> None:
    fam, _, _, unmodelled = _fit({0x10: _rows(2000, 0, 1), 0x30: np.full((1500, F), 0.25)})
    assert unmodelled["0x30"]["reason"] == "no canonical feature varies in training"
    assert fam.status(0x30) == UNMODELLED_ID and fam.status(0x10) == SCORED


def test_min_id_rows_boundary() -> None:
    _, id_models, sparse, _ = _fit({0x1: _rows(cp.MIN_ID_ROWS, 0, 1), 0x2: _rows(cp.MIN_ID_ROWS - 1, 0, 2)})
    assert "0x1" in id_models and "0x2" in sparse


# ── determinism ──────────────────────────────────────────────────────────────

def test_fitting_is_deterministic() -> None:
    parts = {0x10: _rows(2000, 0, 1), 0x20: _rows(1500, 2, 2)}
    fam_a, ida, _, _ = _fit(parts)
    fam_b, idb, _, _ = _fit(parts)
    assert ida == idb
    probe, pid = _rows(300, 1, 9), np.r_[np.full(150, 0x10), np.full(150, 0x20)]
    assert np.array_equal(fam_a.score_rows(probe, pid)[0], fam_b.score_rows(probe, pid)[0])
