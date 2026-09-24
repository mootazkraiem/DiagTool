"""Model / state-classifier consistency: the manifest and the checks behind it.

The anomaly models of a family are only valid for the state classifier they
were trained against. These tests build small, real scikit-learn families in a
temporary directory - nothing under assets/ is read for fixtures or written -
and check that anything which does not provably belong together is refused,
and that a frame which cannot be routed to a trained model is reported as
unresolved rather than given a default state or a zero score.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import joblib
import numpy as np
import pandas as pd
import pytest
from sklearn.cluster import KMeans
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import RobustScaler

from backend.ml.runtime.model_loader import RUNTIME_FEATURE_ORDER
from backend.ml.runtime.model_manifest import (
    MANIFEST_NAME,
    UNRESOLVED,
    ManifestError,
    audit_unmanifested,
    build_manifest,
    load_validated_bundle,
    write_manifest,
)

FAMILY = "test_vehicle"
CLF_FEATS = ["time_diff", "msg_frequency", "byte_diff"]            # training-parity columns
STATE_FEATS = ["time_diff", "rolling_mean_byte_diff", "msg_frequency", "changed_bytes_count"]
REPO = Path(__file__).resolve().parents[2]


# ── fixture family ───────────────────────────────────────────────────────────

def _fit_family(root: Path, *, mapping=None, states=("driving", "idle"), unmodelled=("parking",),
                clf_frame: bool = False, clf_scaler_data=None) -> Path:
    """Write a small, genuinely trained family and its manifest; return its directory."""
    fam = root / FAMILY
    fam.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(7)

    x = rng.normal(size=(600, len(CLF_FEATS))) + np.repeat(np.eye(3, len(CLF_FEATS)) * 6, 200, axis=0)
    if clf_scaler_data is not None:
        x = clf_scaler_data
    scaler = RobustScaler().fit(pd.DataFrame(x, columns=CLF_FEATS) if clf_frame else x)
    kmeans = KMeans(n_clusters=3, random_state=0, n_init=5).fit(scaler.transform(x))
    joblib.dump(scaler, fam / "state_scaler.joblib")
    joblib.dump(kmeans, fam / "kmeans_state_model.joblib")

    state_entries = {}
    for st in states:
        xs = rng.normal(size=(300, len(STATE_FEATS)))
        s_scaler = RobustScaler().fit(xs)
        model = IsolationForest(n_estimators=20, random_state=0).fit(s_scaler.transform(xs))
        joblib.dump(s_scaler, fam / f"scaler_{st}.joblib")
        joblib.dump(model, fam / f"model_{st}.joblib")
        dec = model.decision_function(s_scaler.transform(xs))
        th = float(np.median(dec) - 3 * np.median(np.abs(dec - np.median(dec))))
        state_entries[st] = {"features": STATE_FEATS, "scaler": fam / f"scaler_{st}.joblib",
                             "model": fam / f"model_{st}.joblib", "threshold": th}

    manifest = build_manifest(
        fam,
        family=FAMILY,
        model_version="t1",
        created_at="2026-09-23T00:00:00Z",
        training_pipeline="tests.fixture@1",
        training_corpus={"id": "synthetic-fixture", "sha256": "0" * 64},
        classifier_version="clf-t1",
        classifier_input_space="training_parity",
        classifier_features=CLF_FEATS,
        classifier_scaler=fam / "state_scaler.joblib",
        classifier_kmeans=fam / "kmeans_state_model.joblib",
        mapping=mapping if mapping is not None else {0: "driving", 1: "idle", 2: "parking"},
        states=state_entries,
        unmodelled_states=unmodelled,
    )
    write_manifest(fam, manifest)
    return fam


def _edit_manifest(fam: Path, fn) -> None:
    path = fam / MANIFEST_NAME
    m = json.loads(path.read_text())
    fn(m)
    path.write_text(json.dumps(m))


def _problems(root: Path) -> str:
    with pytest.raises(ManifestError) as info:
        load_validated_bundle(root, FAMILY, runtime_feature_order=RUNTIME_FEATURE_ORDER)
    return "\n".join(info.value.problems)


def _frames(n: int = 900) -> pd.DataFrame:
    rng = np.random.default_rng(3)
    df = pd.DataFrame({"timestamp": np.sort(rng.uniform(0, 30, n)),
                       "can_id": rng.choice([0x100, 0x1A0, 0x2F0, 0x3C4], n)})
    for i in range(8):
        df[f"b{i}"] = rng.integers(0, 256, n)
    return df


class _FixedLabels:
    """Stand-in for KMeans returning chosen cluster labels."""
    cluster_centers_ = np.zeros((3, len(CLF_FEATS)))

    def __init__(self, labels):
        self.labels = np.asarray(labels)

    def predict(self, z):
        return self.labels[: len(z)]


class _Broken:
    cluster_centers_ = np.zeros((3, len(CLF_FEATS)))

    def predict(self, z):
        raise RuntimeError("model file corrupt")


# ── A. a compatible family loads ─────────────────────────────────────────────

def test_A_compatible_family_loads(tmp_path: Path) -> None:
    _fit_family(tmp_path)
    bundle = load_validated_bundle(tmp_path, FAMILY, runtime_feature_order=RUNTIME_FEATURE_ORDER)
    assert set(bundle.models) == {"driving", "idle"}
    assert bundle.unmodelled_states == {"parking"}
    assert bundle.classifier.features == CLF_FEATS


# ── B. feature-count mismatch ────────────────────────────────────────────────

def test_B_classifier_feature_count_mismatch_fails(tmp_path: Path) -> None:
    fam = _fit_family(tmp_path)
    _edit_manifest(fam, lambda m: m["state_classifier"]["features"].append("burstiness"))
    text = _problems(tmp_path)
    assert "scaler expects 3 features, manifest lists 4" in text
    assert "KMeans expects 3 features, manifest lists 4" in text


def test_B_state_model_feature_count_mismatch_fails(tmp_path: Path) -> None:
    fam = _fit_family(tmp_path)
    _edit_manifest(fam, lambda m: m["states"]["idle"]["features"].pop())
    assert "state 'idle': scaler expects 4 features, manifest lists 3" in _problems(tmp_path)


# ── C. feature-order mismatch ────────────────────────────────────────────────

def test_C_feature_order_mismatch_fails(tmp_path: Path) -> None:
    fam = _fit_family(tmp_path, clf_frame=True)       # scaler records feature_names_in_
    _edit_manifest(fam, lambda m: m["state_classifier"].__setitem__(
        "features", [CLF_FEATS[1], CLF_FEATS[0], CLF_FEATS[2]]))
    assert "name or order differs" in _problems(tmp_path)


def test_C_runtime_classifier_must_match_runtime_order(tmp_path: Path) -> None:
    fam = _fit_family(tmp_path)
    _edit_manifest(fam, lambda m: m["state_classifier"].__setitem__("input_space", "runtime"))
    assert "do not match the runtime feature schema" in _problems(tmp_path)


# ── D. near-zero scaler dimension ────────────────────────────────────────────

def test_D_near_zero_classifier_scale_fails(tmp_path: Path) -> None:
    # The defect in the current production classifier: one column fitted on a
    # constant (floating-point residue), leaving a scale of ~2e-10.
    rng = np.random.default_rng(1)
    x = rng.normal(size=(600, 3))
    x[:, 2] = -4.44e-10 + rng.uniform(0.0, 4.44e-10, 600)
    _fit_family(tmp_path, clf_scaler_data=x)
    text = _problems(tmp_path)
    assert "near-zero scale" in text and "byte_diff" in text


# ── E. routed state without a model → explicit unresolved ────────────────────

def test_E_state_without_model_is_unresolved(tmp_path: Path) -> None:
    _fit_family(tmp_path)
    bundle = load_validated_bundle(tmp_path, FAMILY)
    bundle.classifier.kmeans = _FixedLabels([0, 1, 2, 2])
    states, reasons = bundle.resolve_states(np.zeros((4, 3)))
    assert states == ["driving", "idle", UNRESOLVED, UNRESOLVED]
    assert reasons[2] == "no_model_for_state:parking"


def test_E_undeclared_state_without_model_fails_at_load(tmp_path: Path) -> None:
    _fit_family(tmp_path, unmodelled=())
    assert "which has no model and is not declared" in _problems(tmp_path)


# ── F. unmapped cluster → unresolved ─────────────────────────────────────────

def test_F_unmapped_cluster_is_unresolved(tmp_path: Path) -> None:
    _fit_family(tmp_path)
    bundle = load_validated_bundle(tmp_path, FAMILY)
    bundle.classifier.kmeans = _FixedLabels([1, 7])
    states, reasons = bundle.resolve_states(np.zeros((2, 3)))
    assert states == ["idle", UNRESOLVED]
    assert reasons[1] == "unmapped_cluster:7"


def test_F_incomplete_mapping_fails_at_load(tmp_path: Path) -> None:
    _fit_family(tmp_path, mapping={0: "driving", 1: "idle"})
    assert "does not name clusters [2]" in _problems(tmp_path)


# ── G. classifier exception → unresolved ─────────────────────────────────────

def test_G_classifier_exception_marks_every_row_unresolved(tmp_path: Path) -> None:
    _fit_family(tmp_path)
    bundle = load_validated_bundle(tmp_path, FAMILY)
    bundle.classifier.kmeans = _Broken()
    states, reasons = bundle.resolve_states(np.zeros((5, 3)))
    assert states == [UNRESOLVED] * 5
    assert all(r.startswith("classifier_error: RuntimeError") for r in reasons)
    assert bundle.score(states, {}) == [None] * 5          # never a zero score


# ── H. missing feature is an error, not a zero ───────────────────────────────

def test_H_missing_anomaly_feature_fails(tmp_path: Path) -> None:
    _fit_family(tmp_path)
    bundle = load_validated_bundle(tmp_path, FAMILY)
    cols = {f: np.zeros(2) for f in STATE_FEATS if f != "changed_bytes_count"}
    with pytest.raises(ValueError, match="changed_bytes_count"):
        bundle.score(["driving", "idle"], cols)


def test_H_missing_classifier_feature_fails(tmp_path: Path, monkeypatch) -> None:
    fam = _fit_family(tmp_path)
    # A classifier feature training_parity_features does not produce.
    _edit_manifest(fam, lambda m: m["state_classifier"].__setitem__(
        "features", ["time_diff", "msg_frequency", "burstiness"]))
    from backend.ml.runtime import vehicle_scoring
    with pytest.raises(ValueError, match="burstiness"):
        vehicle_scoring.score_frames(_frames(), FAMILY, model_root=tmp_path)


# ── I. classifier replaced under the models ──────────────────────────────────

def test_I_replaced_classifier_fails(tmp_path: Path) -> None:
    fam = _fit_family(tmp_path)
    # Retrain the classifier in place, as happened on 22 June: same shape, new file.
    x = np.random.default_rng(99).normal(size=(600, 3))
    scaler = RobustScaler().fit(x)
    joblib.dump(scaler, fam / "state_scaler.joblib")
    joblib.dump(KMeans(n_clusters=3, random_state=1, n_init=5).fit(scaler.transform(x)),
                fam / "kmeans_state_model.joblib")
    text = _problems(tmp_path)
    assert "state_classifier.scaler" in text and "does not match the file this family was built with" in text
    assert "state_classifier.kmeans" in text


def test_I_replaced_state_model_fails(tmp_path: Path) -> None:
    fam = _fit_family(tmp_path)
    (fam / "model_idle.joblib").write_bytes((fam / "model_driving.joblib").read_bytes())
    assert "state 'idle' model" in _problems(tmp_path)


def test_missing_manifest_fails(tmp_path: Path) -> None:
    fam = _fit_family(tmp_path)
    (fam / MANIFEST_NAME).unlink()
    assert "no manifest.json" in _problems(tmp_path)


def test_non_finite_threshold_fails(tmp_path: Path) -> None:
    fam = _fit_family(tmp_path)
    _edit_manifest(fam, lambda m: m["states"]["driving"].__setitem__("threshold", None))
    assert "threshold missing or not a finite number" in _problems(tmp_path)


def test_every_problem_is_reported_at_once(tmp_path: Path) -> None:
    fam = _fit_family(tmp_path)
    _edit_manifest(fam, lambda m: (m["states"]["driving"].__setitem__("threshold", "x"),
                                   m["state_classifier"].__setitem__("mapping", {"0": "driving"})))
    text = _problems(tmp_path)
    assert "threshold" in text and "does not name clusters" in text


# ── J. a valid manifest loads and scores end to end ──────────────────────────

def test_J_manifest_round_trip_scores_every_frame(tmp_path: Path) -> None:
    from backend.ml.runtime.vehicle_scoring import score_frames

    _fit_family(tmp_path)
    frames = _frames()
    scored = score_frames(frames, FAMILY, model_root=tmp_path)

    assert len(scored) == len(frames)
    assert list(scored["timestamp"]) == list(frames["timestamp"])
    assert set(scored["anomaly"].unique()) <= {-1, 0, 1}
    resolved = scored["vehicle_state"] != UNRESOLVED
    assert scored.loc[resolved, "anomaly_score"].between(0.0, 1.0).all()
    assert scored.loc[resolved, "anomaly"].isin([-1, 1]).all()
    # Unresolved rows carry no score, no verdict and a reason.
    assert scored.loc[~resolved, "anomaly_score"].isna().all()
    assert (scored.loc[~resolved, "anomaly"] == 0).all()
    assert (scored.loc[~resolved, "cluster"] == -1).all()
    assert (scored.loc[~resolved, "state_resolution"] != "").all()
    assert (scored.loc[resolved, "state_resolution"] == "").all()


# ── the artifacts actually shipped ───────────────────────────────────────────

def test_current_vehicle_families_are_refused_not_scored() -> None:
    """No production family carries a manifest, so none may be scored offline."""
    from backend.ml.runtime.model_loader import list_available_models
    from backend.ml.runtime.vehicle_scoring import score_frames

    vehicles = [m["id"] for m in list_available_models() if m["id"] != "general"]
    assert vehicles
    for family in vehicles:
        with pytest.raises(ManifestError, match="no manifest.json"):
            score_frames(_frames(50), family)


def test_audit_reports_the_degenerate_production_classifier() -> None:
    found = audit_unmanifested(REPO / "assets" / "models", "skoda_enyaq", RUNTIME_FEATURE_ORDER)
    text = "\n".join(found)
    assert "no manifest" in text
    assert "near-zero scale" in text and "can_id_entropy" in text
    assert "routes cluster 0 to 'parking', which has no model in this family" in text
