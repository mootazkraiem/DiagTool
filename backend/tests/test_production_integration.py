"""Production integration: the promoted clean-2 families are what the runtime selects.

Runs against the real assets/models (commit 9029fdd) and never writes to it. Covers
the scoring outcome per frame (scored / sparse / unseen / warm-up), which families are
clean-2, and that a broken production family fails loudly instead of falling back.
"""
from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
import pandas as pd
import pytest

from backend.ml.features import canonical
from backend.ml.runtime.model_manifest import (
    ID_SCHEMA_VERSION,
    IdModelFamily,
    ManifestError,
    load_any_family,
    manifest_schema,
)

REPO = Path(__file__).resolve().parents[2]
PROD = REPO / "assets" / "models"
PROMOTED = ("jaguar_ipace", "kia_ev6", "nissan_leaf_2019", "road_ambient")
FAMILY = "nissan_leaf_2019"


def _manifest(family: str) -> dict:
    return json.loads((PROD / family / "manifest.json").read_text(encoding="utf-8"))


def _ids(family: str) -> tuple[int, int, int]:
    """A modelled ID, a sparse ID and an ID absent from every manifest list."""
    m = _manifest(family)
    known = int(sorted(m["id_models"])[0], 16)
    sparse = int(sorted(m["sparse_ids"])[0], 16)
    listed = {int(k, 16) for k in (*m["id_models"], *m["sparse_ids"], *m["unmodelled_ids"])}
    unseen = next(c for c in range(0x7FF, 0, -1) if c not in listed)
    return known, sparse, unseen


def _stream(ids: list[int], frames_each: int = 30) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    rows, t = [], 0.0
    for i in range(frames_each):
        for cid in ids:
            rows.append([t, cid, i % 256, *rng.integers(0, 4, 7).tolist()])
            t += 0.01 + rng.uniform(0, 0.0005)
    return pd.DataFrame(rows, columns=["timestamp", "can_id", *[f"b{i}" for i in range(8)]])


def _engine(vehicle_id: str, **kw):
    from backend.ml.runtime.realtime_engine import RealtimeEngine
    with contextlib.redirect_stdout(io.StringIO()):
        return RealtimeEngine(vehicle_id=vehicle_id, **kw)


# ── 1-4: per-frame outcome through the offline production path ───────────────

@pytest.fixture(scope="module")
def scored() -> tuple[pd.DataFrame, tuple[int, int, int]]:
    from backend.ml.runtime.vehicle_scoring import score_frames
    ids = _ids(FAMILY)
    return score_frames(_stream(list(ids)), FAMILY), ids


def _reason(df: pd.DataFrame) -> pd.Series:
    return df["state_resolution"].astype(str).str.split(":").str[0]


def test_known_id_is_scored_by_its_own_model(scored) -> None:
    df, (known, _, _) = scored
    rows = df[(df["can_id"] == known) & (_reason(df) == "")]
    assert len(rows) == 30 - canonical.WINDOW
    assert rows["anomaly"].isin([-1, 1]).all() and rows["anomaly_score"].between(0, 1).all()
    assert (rows["vehicle_state"] == "can_id_model").all()


def test_sparse_id_is_unresolved_without_score(scored) -> None:
    df, (_, sparse, _) = scored
    rows = df[(df["can_id"] == sparse) & (_reason(df) != "warmup")]
    assert (_reason(rows) == "sparse_id").all() and len(rows) == 30 - canonical.WINDOW
    assert (rows["anomaly"] == 0).all() and rows["anomaly_score"].isna().all()


def test_unseen_id_is_unresolved_without_score(scored) -> None:
    df, (_, _, unseen) = scored
    rows = df[(df["can_id"] == unseen) & (_reason(df) != "warmup")]
    assert (_reason(rows) == "unseen_id").all() and len(rows) == 30 - canonical.WINDOW
    assert (rows["anomaly"] == 0).all() and rows["anomaly_score"].isna().all()


def test_warmup_frames_are_unresolved(scored) -> None:
    df, ids = scored
    for cid in ids:
        first = df[df["can_id"] == cid].head(canonical.WINDOW)
        assert (_reason(first) == "warmup").all() and (first["anomaly"] == 0).all()


def test_no_unresolved_frame_is_counted_as_anomaly(scored) -> None:
    df, _ = scored
    unresolved = _reason(df) != ""
    assert (df.loc[unresolved, "anomaly"] == 0).all()
    assert int((df["anomaly"] == -1).sum()) + int((df["anomaly"] == 1).sum()) + int(unresolved.sum()) == len(df)


def test_live_engine_reports_the_same_statuses() -> None:
    from backend.ml.runtime.realtime_engine import CanFrame
    known, sparse, unseen = _ids(FAMILY)
    engine = _engine(FAMILY)
    states: dict[int, set[str]] = {}
    for r in _stream([known, sparse, unseen]).itertuples(index=False):
        out = engine.process_frame(CanFrame(r.timestamp, int(r.can_id), tuple(int(getattr(r, f"b{i}")) for i in range(8))))
        states.setdefault(int(r.can_id), set()).add(out["vehicle_state"])
    assert states[known] == {"warmup", "can_id_model"}
    assert states[sparse] == {"warmup", "sparse_id"}
    assert states[unseen] == {"warmup", "unseen_id"}


# ── 5-8: which families are clean-2 ──────────────────────────────────────────

@pytest.mark.parametrize("family", PROMOTED)
def test_promoted_family_is_schema_3_clean_2(family) -> None:
    assert manifest_schema(PROD, family) == ID_SCHEMA_VERSION
    fam = load_any_family(PROD, family)
    assert isinstance(fam, IdModelFamily)
    assert fam.manifest["model_version"] == "clean-2-002"
    assert fam.manifest["validation"]["status"] == "holdout_evaluated"
    assert isinstance(_engine(family)._family, IdModelFamily)


@pytest.mark.parametrize("family", ["mg_zs_ev", "skoda_enyaq", "hyundai_ioniq5", "kaggle_normal", "tesla", "nissan_leaf"])
def test_non_promoted_family_is_not_clean_2(family) -> None:
    from backend.ml.runtime.vehicle_scoring import score_frames
    assert manifest_schema(PROD, family) is None
    assert _engine(family)._family is None
    with pytest.raises(ManifestError, match="no manifest.json"):
        score_frames(_stream([0x100]), family)


def test_legacy_family_keeps_the_legacy_path() -> None:
    engine = _engine("tesla")
    assert engine._family is None
    assert engine.models.bundle_for("tesla") is not None


# ── 9-10: explicit behaviour for wrong selections and broken production ──────

def test_unknown_vehicle_is_refused_by_offline_vehicle_scoring() -> None:
    from backend.ml.runtime.vehicle_scoring import score_frames
    with pytest.raises(ManifestError, match="no manifest.json"):
        score_frames(_stream([0x100]), "no_such_vehicle")
    assert _engine("no_such_vehicle")._family is None


def test_broken_production_family_fails_loudly(tmp_path) -> None:
    from backend.ml.runtime.vehicle_scoring import score_frames
    shutil.copytree(PROD / FAMILY, tmp_path / FAMILY)
    (tmp_path / FAMILY / "models.joblib").write_bytes(b"corrupt")
    with pytest.raises(ManifestError, match="does not match"):
        load_any_family(tmp_path, FAMILY)
    with pytest.raises(ManifestError):
        _engine(FAMILY, model_root=tmp_path)
    with pytest.raises(ManifestError):
        score_frames(_stream([0x9]), FAMILY, model_root=tmp_path)


# ── live hardware model selection (Step 12, P0-3) ────────────────────────────

def _live(vehicle_id: str, **kw):
    from backend.ml.runtime.model_status import live_engine
    with contextlib.redirect_stdout(io.StringIO()):
        return live_engine(vehicle_id, **kw)


@pytest.mark.parametrize("family", ["kia_ev6", "jaguar_ipace", "nissan_leaf_2019", "road_ambient"])
def test_live_hardware_engine_is_schema_3_clean_2(family) -> None:
    engine = _live(family)
    assert isinstance(engine._family, IdModelFamily)
    assert engine._family.family == family
    assert engine._family.manifest["model_version"] == "clean-2-002"
    assert engine.model_status.live == "clean_2"


def test_live_legacy_vehicle_uses_the_explicit_legacy_path() -> None:
    engine = _live("bmw_i3")
    assert engine._family is None
    assert engine.model_status.status == "legacy" and engine.model_status.live == "legacy"
    assert engine.models.bundle_for("bmw_i3") is not None


@pytest.mark.parametrize("vehicle, status", [("mg_zs_ev", "clean_held_back"),
                                             ("skoda_enyaq", "unavailable_no_clean_model"),
                                             ("nissan_leaf", "unavailable_no_clean_model"),
                                             ("no_such_vehicle", "unknown")])
def test_live_refuses_unavailable_selections_explicitly(vehicle, status) -> None:
    from backend.ml.runtime.model_status import ModelUnavailableError
    with pytest.raises(ModelUnavailableError) as info:
        _live(vehicle)
    assert info.value.status.status == status
    assert vehicle in str(info.value) and status in str(info.value)


def test_live_schema_3_validation_failure_never_falls_back(tmp_path) -> None:
    shutil.copytree(PROD / FAMILY, tmp_path / FAMILY)
    (tmp_path / FAMILY / "models.joblib").write_bytes(b"corrupt")
    with pytest.raises(ManifestError):
        _live(FAMILY, model_root=tmp_path)


def _reader():
    import threading
    from backend.hardware.can_interface import CanHardwareReader
    from backend.ml.runtime.model_status import live_engine
    return CanHardwareReader(None, None, [], [], threading.Lock(),
                             engine_factory=lambda vid: _quiet(live_engine, vid))


def _quiet(fn, *a):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a)


def test_hardware_reader_builds_the_selected_engine_and_replaces_it() -> None:
    pytest.importorskip("can")
    reader = _reader()
    reader.connect("virtual", channel="step12", vehicle_id="kia_ev6")
    first = reader._engine
    try:
        assert first._family.family == "kia_ev6"
        assert reader.status()["model_status"]["status"] == "clean_holdout_evaluated"
    finally:
        reader.disconnect()
    assert reader._engine is None                                    # model dropped on disconnect
    reader.connect("virtual", channel="step12", vehicle_id="jaguar_ipace")
    try:
        assert reader._engine is not first and reader._engine._family.family == "jaguar_ipace"
    finally:
        reader.disconnect()


def test_hardware_reader_refuses_before_opening_the_bus() -> None:
    from backend.ml.runtime.model_status import ModelUnavailableError
    reader = _reader()
    with pytest.raises(ModelUnavailableError):
        reader.connect("virtual", channel="step12", vehicle_id="mg_zs_ev")
    assert not reader.is_connected and reader._bus is None
