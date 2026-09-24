"""Clean model generation: corpus rules, split, validation, staging and promotion.

Everything runs against a synthetic assets tree in a temporary directory. The
real assets/models is never read as a fixture or written.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
import pandas as pd
import pytest

from backend.ml.features import canonical
from backend.ml.runtime.model_manifest import ManifestError, load_id_family, load_validated_bundle
from backend.ml.training import clean_pipeline as cp
from backend.ml.training import model_promotion as mp
from backend.ml.training import recordings as rec

REPO = Path(__file__).resolve().parents[2]


# ── synthetic corpus ─────────────────────────────────────────────────────────

def _traffic(seconds: float, seed: int, t0: float = 1_600_000_000.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for cid, period in ((0x100, 0.010), (0x200, 0.020), (0x300, 0.050)):
        t, counter, level = 0.0, 0, 100
        while t < seconds:
            level = int(np.clip(level + rng.integers(-2, 3), 0, 255))
            payload = [counter & 0xFF, level, *rng.integers(0, 4, 6).tolist()]
            rows.append([t0 + t + rng.uniform(0, 0.0008), cid, *payload])
            counter += 1
            t += period
    df = pd.DataFrame(rows, columns=rec.COLUMNS).sort_values("timestamp", kind="mergesort")
    return df.reset_index(drop=True)


def _write_candump(path: Path, df: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        for r in df.itertuples(index=False):
            data = "".join(f"{int(getattr(r, f'b{i}')):02X}" for i in range(8))
            fh.write(f"({r.timestamp:.6f}) can0 {int(r.can_id):03X}#{data}\n")


def _write_generic_csv(path: Path, df: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.assign(timestamp=df["timestamp"] - df["timestamp"].min()).to_csv(path, index=False)


RARE_ID = 0x7E0            # 5 frames in rec_a only: seen in training, but never a ready feature row


def _with_rare(df: pd.DataFrame) -> pd.DataFrame:
    t0 = float(df["timestamp"].iloc[0])
    rare = pd.DataFrame([[t0 + 1.0 + i, RARE_ID, 2, 1, 0, 0, 0, 0, 0, i] for i in range(5)], columns=rec.COLUMNS)
    return pd.concat([df, rare]).sort_values("timestamp", kind="mergesort").reset_index(drop=True)


def _make_assets(root: Path) -> Path:
    ev = root / "EV-CANlogs-main"
    a, b, c = _with_rare(_traffic(12, 1)), _traffic(12, 2), _traffic(12, 3)
    _write_candump(ev / "Alpha Car" / "rec_a.log", a)
    _write_candump(ev / "Alpha Car" / "rec_b.log", b)
    _write_candump(ev / "Alpha Car" / "rec_c.log", c)
    _write_candump(ev / "Alpha Car" / "rec_dup.log", a.assign(timestamp=a["timestamp"] + 500))
    _write_candump(ev / "Beta Car" / "only.log", _traffic(20, 4))
    (ev / "Beta Car" / "busmaster.log").write_text("ParserFlags\tCh\tCounter\tT/R\tTime\n1\t0\t1\tRX\t100\n")
    (ev / "Beta Car" / "pcan.txt").write_text("1512293  5F1  8  A8 16 65 9 0 0 0 0\n")
    g1, g2 = _traffic(15, 5), _traffic(15, 6)
    _write_candump(ev / "Gamma Car" / "g1.log", g1)
    _write_candump(ev / "Gamma Car" / "g2.log", g2)
    _write_generic_csv(root / "Skoda Enyaq" / "file_16.csv", g2)          # protected == g2
    e1, e2 = _traffic(15, 8), _traffic(15, 10)
    _write_candump(ev / "Echo Car" / "e1.log", e1)
    _write_candump(ev / "Echo Car" / "e2.log", e2)
    _write_generic_csv(root / "Skoda Enyaq" / "file_12.csv", e1.iloc[:1200])   # protected slice of e1
    s1, s2 = _traffic(15, 13), _traffic(15, 14)
    _write_candump(ev / "Sierra Car" / "s1.log", s1)
    _write_candump(ev / "Sierra Car" / "s2.log", s2)
    _write_generic_csv(root / "Skoda Enyaq" / "file_13.csv", s1)                # s1 in full
    _write_generic_csv(root / "Skoda Enyaq" / "file_14.csv", s2.iloc[:2000])    # slice of s2
    bad = _traffic(12, 7)
    _write_candump(ev / "Delta Car" / "flood.log", bad.assign(timestamp=bad["timestamp"] / 1000))
    chd = root / "9) Car-Hacking Dataset"
    chd.mkdir(parents=True)
    (chd / "DoS_dataset.csv").write_text("1478193190.056566,0140,8,00,00,00,00,10,29,2a,24,R\n")
    (root / "models" / "legacy").mkdir(parents=True)
    (root / "models" / "legacy" / "model_idle.joblib").write_bytes(b"legacy")
    return root


def _tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        h.update(p.relative_to(root).as_posix().encode())
        if p.is_file():
            h.update(p.read_bytes())
    return h.hexdigest()


@pytest.fixture(scope="module")
def assets(tmp_path_factory) -> Path:
    return _make_assets(tmp_path_factory.mktemp("assets"))


@pytest.fixture(scope="module")
def plan(assets) -> cp.TrainingPlan:
    return cp.build_plan(assets, log=lambda *_: None,
                         protected_files=PROTECTED)


PROTECTED = ("Skoda Enyaq/file_16.csv", "Skoda Enyaq/file_12.csv",
             "Skoda Enyaq/file_13.csv", "Skoda Enyaq/file_14.csv")


@pytest.fixture(scope="module")
def staged(assets, plan) -> Path:
    before = _tree_hash(assets / "models")
    out = cp.train("t1", assets_root=assets, plan=plan, log=lambda *_: None)
    assert _tree_hash(assets / "models") == before, "training touched the production root"
    return out


def _status(plan, name):
    return next(r for r in plan.recordings if r.path.endswith(name))


# ── timestamps and formats ───────────────────────────────────────────────────

def _ts_frame(ts) -> pd.DataFrame:
    n = len(ts)
    return pd.DataFrame({"timestamp": ts, "can_id": [1] * n, **{f"b{i}": [0] * n for i in range(8)}})


@pytest.mark.parametrize("ts, reason", [
    (np.linspace(-5, 5, 2000), "negative"),
    (np.full(2000, 7.0), "zero duration"),
    (np.linspace(0, 0.01, 2000), "physical bus limit"),
    (np.linspace(0, 1e6, 2000), "implausibly sparse"),
    (np.r_[np.linspace(0, 5, 1000), np.linspace(0, 5, 1000)], "jumps backwards"),
    (np.tile([0.0, 0.004, 0.002, 0.006], 500) + np.repeat(np.arange(500) * 0.008, 4), "go backwards"),
    (np.r_[np.linspace(0, 5, 1000), 7200 + np.linspace(0, 5, 1000)], "gap"),
    (np.linspace(0, 1, 50), "minimum"),
])
def test_implausible_timing_is_rejected_not_repaired(ts, reason) -> None:
    assert any(reason in p for p in rec.timestamp_problems(_ts_frame(ts)))


def test_plausible_timing_passes() -> None:
    assert rec.timestamp_problems(_ts_frame(np.linspace(0, 10, 3000))) == []


def test_unitless_and_timeless_formats_are_excluded(plan) -> None:
    assert "does not state its unit" in _status(plan, "busmaster.log").reason
    assert "does not state its unit" in _status(plan, "pcan.txt").reason
    assert _status(plan, "busmaster.log").status == "excluded"


def test_flood_rate_recording_is_excluded(plan) -> None:
    r = _status(plan, "flood.log")
    assert r.status == "excluded" and "physical bus limit" in r.reason


def test_attack_session_captures_are_excluded_by_policy(plan) -> None:
    r = _status(plan, "DoS_dataset.csv")
    assert r.status == "excluded" and "attack" in r.reason


def test_frame_cap_keeps_a_contiguous_prefix(tmp_path) -> None:
    df = _traffic(10, 9)
    _write_candump(tmp_path / "x.log", df)
    full = rec.load_recording(rec.Recording("v", tmp_path / "x.log", "candump_ts"))
    capped = rec.load_recording(rec.Recording("v", tmp_path / "x.log", "candump_ts", frame_cap=500))
    assert len(capped) == 500
    pd.testing.assert_frame_equal(capped, full.iloc[:500].reset_index(drop=True))


# ── split and leakage ────────────────────────────────────────────────────────

def test_recording_level_holdout(plan) -> None:
    assert _status(plan, "rec_c.log").status == "holdout"          # last by path
    assert {_status(plan, n).status for n in ("rec_a.log", "rec_b.log")} == {"train"}


def test_identical_traffic_is_deduplicated(plan) -> None:
    r = _status(plan, "rec_dup.log")
    assert r.status == "excluded" and "identical traffic" in r.reason


def test_protected_evaluation_recording_is_never_trained_on(plan) -> None:
    g2 = _status(plan, "g2.log")
    assert g2.status == "holdout" and "protected evaluation file" in g2.reason
    assert _status(plan, "g1.log").status == "train"


def test_recording_containing_a_protected_slice_is_never_trained_on(plan) -> None:
    e1 = _status(plan, "e1.log")
    assert e1.status == "holdout" and "contains protected evaluation file Skoda Enyaq/file_12.csv" in e1.reason
    assert _status(plan, "e2.log").status == "train"


def test_family_with_only_protected_recordings_gets_no_training(plan) -> None:
    assert {_status(plan, n).status for n in ("s1.log", "s2.log")} == {"holdout"}
    assert plan.families["sierra_car"]["status"] == "excluded"
    assert plan.families["sierra_car"]["training_recordings"] == 0


def test_no_protected_traffic_in_any_training_recording(assets, plan) -> None:
    """Re-derive from the files: no training recording holds protected traffic."""
    protected = cp._protected_recordings(assets, PROTECTED)
    for r in plan.by_status("train"):
        frames = rec.load_recording(rec.Recording(r.vehicle, assets / r.path, r.fmt, r.frame_cap))
        assert cp.protection_reason(r.content_sha256, rec.traffic_rows(frames), protected) == "", r.path


def test_missing_protected_file_is_an_error(assets) -> None:
    with pytest.raises(FileNotFoundError, match="protected evaluation file missing"):
        cp.build_plan(assets, log=lambda *_: None, protected_files=("Skoda Enyaq/file_99.csv",))


def test_containment_check() -> None:
    big = rec.traffic_rows(_traffic(5, 1))
    assert rec.contains(big, big[100:400])
    assert not rec.contains(big, rec.traffic_rows(_traffic(5, 2))[:50])


def test_policy_excluded_family_is_not_trained(assets, monkeypatch) -> None:
    monkeypatch.setitem(cp.EXCLUDED_FAMILIES, "alpha_car", "test policy")
    plan = cp.build_plan(assets, log=lambda *_: None, protected_files=PROTECTED)
    assert plan.families["alpha_car"]["status"] == "excluded"
    assert plan.families["alpha_car"]["reason"] == "test policy"
    alpha = [r for r in plan.recordings if r.vehicle == "alpha_car"]
    assert alpha and not any(r.status in ("train", "holdout") for r in alpha)
    assert all("test policy" in r.reason or "identical traffic" in r.reason for r in alpha)


def test_nissan_leaf_is_excluded_by_policy() -> None:
    assert "nissan_leaf" in cp.EXCLUDED_FAMILIES
    assert "nissan_leaf_2019" not in cp.EXCLUDED_FAMILIES


def test_single_recording_family_has_no_holdout(plan) -> None:
    assert _status(plan, "only.log").status == "train"
    assert plan.families["beta_car"]["holdout_recordings"] == 0


def test_leakage_check_raises(plan) -> None:
    import copy
    leaky = copy.deepcopy(plan)
    next(r for r in leaky.recordings if r.path.endswith("rec_c.log")).content_sha256 = \
        next(r for r in leaky.recordings if r.path.endswith("rec_a.log")).content_sha256
    with pytest.raises(cp.LeakageError):
        cp.check_no_leakage(leaky)


# ── feature validation ───────────────────────────────────────────────────────

def test_constant_feature_is_dropped_with_its_value() -> None:
    rng = np.random.default_rng(0)
    x = rng.normal(size=(3000, len(canonical.FEATURES)))
    x[:, canonical.FEATURES.index("payload_entropy")] = 1.5
    kept, constant = cp.varying_features(x)
    assert "payload_entropy" not in kept and constant == {"payload_entropy": 1.5}


def test_rarely_changing_feature_is_kept() -> None:
    """IQR 0 is not constant: a feature that changes on a few rows still separates them."""
    x = np.zeros((3000, len(canonical.FEATURES)))
    x[::97, canonical.FEATURES.index("byte_diff")] = 2.0
    kept, _ = cp.varying_features(x)
    assert "byte_diff" in kept


def test_nan_features_are_rejected() -> None:
    x = np.zeros((10, len(canonical.FEATURES)))
    x[3, 2] = np.nan
    with pytest.raises(ValueError, match="NaN or Inf"):
        cp.varying_features(x)


# ── staging ──────────────────────────────────────────────────────────────────

def test_refuses_to_write_into_production(assets) -> None:
    with pytest.raises(ValueError, match="production model root"):
        cp._output_dir(assets, "v1", assets / "models")
    with pytest.raises(ValueError, match="invalid version"):
        cp._output_dir(assets, "../escape", None)


def test_staged_version_is_never_overwritten(assets, staged) -> None:
    with pytest.raises(FileExistsError):
        cp._output_dir(assets, "t1", None)


def test_staged_families_validate_and_carry_their_corpus(staged, plan) -> None:
    families = mp.validate_staging(staged)
    assert set(families) == {"alpha_car", "beta_car", "gamma_car", "echo_car"}   # sierra_car: all protected
    m = families["alpha_car"].manifest
    assert m["schema_version"] == 3 and m["feature_pipeline"]["version"] == canonical.FEATURE_VERSION
    assert m["model_params"]["scaler"] is None
    trained = {r["path"] for r in m["training_corpus"]["recordings"]}
    held = {r["path"] for r in m["holdout"]["recordings"]}
    assert trained == {"EV-CANlogs-main/Alpha Car/rec_a.log", "EV-CANlogs-main/Alpha Car/rec_b.log"}
    assert held == {"EV-CANlogs-main/Alpha Car/rec_c.log"}
    for f in ("models.joblib", "features.json", "thresholds.json", "corpus.json", "manifest.json"):
        assert (staged / "alpha_car" / f).is_file()
    for f in ("training_report.json", "corpus.json", "pipeline.json"):
        assert (staged / f).is_file()
    report = json.loads((staged / "training_report.json").read_text())
    assert report["results"]["alpha_car"]["holdout_evaluation"][0]["rows"] > 0


def test_offline_scoring_with_a_staged_family(staged) -> None:
    from backend.ml.runtime.vehicle_scoring import score_frames

    frames = _traffic(5, 11)
    scored = score_frames(frames, "alpha_car", model_root=staged)
    reason = scored["state_resolution"].str.split(":").str[0]
    assert (reason == "warmup").sum() == 3 * canonical.WINDOW          # first WINDOW frames of each of 3 IDs
    assert set(reason) == {"", "warmup", "sparse_id"}                   # 0x300 has too few training rows
    ok = reason == ""
    assert scored.loc[ok, "anomaly_score"].between(0, 1).all()
    assert scored.loc[ok, "anomaly"].isin([-1, 1]).all()
    assert (scored.loc[~ok, "anomaly"] == 0).all() and scored.loc[~ok, "anomaly_score"].isna().all()


def test_live_engine_scores_exactly_like_offline(staged) -> None:
    """Same frames, same family: the live engine's model scores equal the batch ones."""
    from backend.ml.runtime.realtime_engine import CanFrame, RealtimeEngine
    from backend.ml.runtime.vehicle_scoring import score_frames

    frames = _traffic(4, 12)
    offline = score_frames(frames, "alpha_car", model_root=staged)
    engine = RealtimeEngine(vehicle_id="alpha_car", model_root=staged)
    live_norm, live_state = [], []
    for r in frames.itertuples(index=False):
        out = engine.process_frame(CanFrame(r.timestamp, int(r.can_id), tuple(int(getattr(r, f"b{i}")) for i in range(8))))
        live_norm.append(out["ml_norm"])
        live_state.append(out["vehicle_state"])
    live_state = np.array(live_state)
    # the live engine re-scores every _ML_STRIDE frames per ID; compare where it scored this frame
    from backend.ml.runtime.realtime_engine import _ML_STRIDE
    counts: dict[int, int] = {}
    fresh = []
    for cid in frames["can_id"]:
        counts[cid] = counts.get(cid, 0) + 1
        fresh.append(counts[cid])
    fresh = np.array(fresh)
    ok = (offline["state_resolution"] == "").to_numpy()
    assert (live_state[ok] == "can_id_model").all()
    assert set(live_state[~ok]) <= {"warmup", "sparse_id"}
    first = np.zeros(len(frames), dtype=bool)
    seen: set[int] = set()
    for i, (cid, good) in enumerate(zip(frames["can_id"], ok)):
        if good and cid not in seen:
            first[i] = True
            seen.add(cid)
    check = ok & ((fresh % _ML_STRIDE == 0) | first)
    assert check.sum() > 50
    assert np.array_equal(np.asarray(live_norm)[check], offline["anomaly_score"].to_numpy()[check])


# ── schema 3 validation ──────────────────────────────────────────────────────

def _copy_family(staged: Path, tmp: Path) -> Path:
    import shutil
    shutil.copytree(staged / "alpha_car", tmp / "alpha_car")
    return tmp


def _edit(root: Path, fn) -> None:
    p = root / "alpha_car" / "manifest.json"
    m = json.loads(p.read_text())
    fn(m)
    p.write_text(json.dumps(m))


def _first_id(m: dict) -> dict:
    return m["id_models"][sorted(m["id_models"])[0]]


def test_tampered_models_file_fails(staged, tmp_path) -> None:
    root = _copy_family(staged, tmp_path)
    (root / "alpha_car" / "models.joblib").write_bytes(b"x")
    with pytest.raises(ManifestError, match="does not match"):
        load_id_family(root, "alpha_car")


def test_other_feature_pipeline_version_fails(staged, tmp_path) -> None:
    root = _copy_family(staged, tmp_path)
    _edit(root, lambda m: m["feature_pipeline"].__setitem__("version", "canonical-0"))
    with pytest.raises(ManifestError, match="feature pipeline"):
        load_id_family(root, "alpha_car")


def test_feature_the_runtime_cannot_produce_fails(staged, tmp_path) -> None:
    root = _copy_family(staged, tmp_path)
    _edit(root, lambda m: _first_id(m)["features"].__setitem__(0, "rolling_min_byte_diff"))
    with pytest.raises(ManifestError, match="not produced by the canonical runtime"):
        load_id_family(root, "alpha_car")


def test_training_holdout_overlap_fails(staged, tmp_path) -> None:
    root = _copy_family(staged, tmp_path)
    _edit(root, lambda m: m["holdout"]["recordings"].append(m["training_corpus"]["recordings"][0]))
    with pytest.raises(ManifestError, match="both training and holdout"):
        load_id_family(root, "alpha_car")


def test_schema_1_loader_refuses_a_schema_3_family(staged) -> None:
    with pytest.raises(ManifestError, match="unsupported schema_version 3"):
        load_validated_bundle(staged, "alpha_car")


def test_live_engine_refuses_an_invalid_family(staged, tmp_path) -> None:
    from backend.ml.runtime.realtime_engine import RealtimeEngine

    root = _copy_family(staged, tmp_path)
    (root / "alpha_car" / "models.joblib").write_bytes(b"x")
    with pytest.raises(ManifestError):
        RealtimeEngine(vehicle_id="alpha_car", model_root=root)


# ── promotion ────────────────────────────────────────────────────────────────

def test_invalid_staging_never_reaches_production(staged, tmp_path) -> None:
    import shutil
    bad = tmp_path / "staging" / "bad"
    shutil.copytree(staged, bad)
    (bad / "beta_car" / "models.joblib").write_bytes(b"x")
    prod = tmp_path / "models"
    (prod / "alpha_car").mkdir(parents=True)
    (prod / "alpha_car" / "model_idle.joblib").write_bytes(b"old")
    before = _tree_hash(prod)
    with pytest.raises(mp.PromotionError, match="failed validation"):
        mp.promote(bad, prod, tmp_path / "archive")
    assert _tree_hash(prod) == before


def test_promotion_swaps_in_validated_families_and_archives_the_old(staged, tmp_path) -> None:
    from backend.ml.runtime.model_loader import list_available_models

    assets = tmp_path / "assets"
    prod = assets / "models"
    (prod / "alpha_car").mkdir(parents=True)
    (prod / "alpha_car" / "model_idle.joblib").write_bytes(b"old")
    (prod / "untouched").mkdir()
    (prod / "untouched" / "x.bin").write_bytes(b"keep")
    record = mp.promote(staged, prod, assets / "models_archive", families=["alpha_car"])

    assert record["families"] == ["alpha_car"] and record["archived"] == ["alpha_car"]
    assert (Path(record["archive_dir"]) / "alpha_car" / "model_idle.joblib").read_bytes() == b"old"
    assert (prod / "untouched" / "x.bin").read_bytes() == b"keep"
    assert not any(p.name.startswith(".incoming") for p in prod.iterdir())
    load_id_family(prod, "alpha_car")
    listed = {m["id"]: m for m in list_available_models(assets)}
    assert listed["alpha_car"]["kind"] == "per_can_id"


def test_real_production_models_are_untouched_by_this_module() -> None:
    """The module's defaults point at staging; the real assets/models has no clean family yet."""
    assert cp.staging_root() == REPO / "assets" / "models_staging"
    assert cp.production_root() == REPO / "assets" / "models"
    assert not any((p / "manifest.json").is_file() for p in (REPO / "assets" / "models").iterdir() if p.is_dir())


CLEAN_1 = REPO / "assets" / "models_staging" / "clean-1-001"


@pytest.mark.skipif(not CLEAN_1.is_dir(), reason="clean-1-001 reference version not present")
def test_clean_1_reference_version_still_validates() -> None:
    """The schema-2 experiment stays loadable as a reference; nothing here rewrites it."""
    families = mp.validate_staging(CLEAN_1)
    assert len(families) == 9
    assert all(f.manifest["schema_version"] == 2 for f in families.values())


# ── calibration metadata recorded and checked ────────────────────────────────

def test_manifest_records_calibration(staged) -> None:
    m = json.loads((staged / "alpha_car" / "manifest.json").read_text())
    assert m["calibration"]["method"] == "empirical_quantile_strict"
    assert m["calibration"]["target_contamination"] == cp.TARGET_CONTAMINATION
    assert m["min_id_rows"] == cp.MIN_ID_ROWS
    for key, e in m["id_models"].items():
        assert e["k"] == int(cp.TARGET_CONTAMINATION * e["rows"]) and 0 <= e["flagged_count"] <= e["k"]
        assert e["median"] > e["threshold"] and e["rows"] >= cp.MIN_ID_ROWS
    assert "0x300" in m["sparse_ids"]


@pytest.mark.parametrize("mutate, message", [
    (lambda m: _first_id(m).__setitem__("k", _first_id(m)["k"] + 1), "does not equal floor"),
    (lambda m: _first_id(m).__setitem__("flagged_count", _first_id(m)["k"] + 1), "flagged_count"),
    (lambda m: _first_id(m).__setitem__("median", _first_id(m)["threshold"]), "is not above threshold"),
    (lambda m: _first_id(m).__setitem__("threshold", float("nan")), "not finite"),
    (lambda m: _first_id(m).__setitem__("rows", 10), "below min_id_rows"),
    (lambda m: m["calibration"].__setitem__("method", "median_minus_kmad"), "unknown calibration method"),
    (lambda m: m["sparse_ids"].__setitem__("0x300", {"rows": 50_000}), "sparse means fewer than"),
    (lambda m: m["id_models"].pop(sorted(m["id_models"])[0]), "disagree on CAN IDs"),
])
def test_inconsistent_calibration_metadata_fails(staged, tmp_path, mutate, message) -> None:
    root = _copy_family(staged, tmp_path)
    _edit(root, mutate)
    with pytest.raises(ManifestError, match=message):
        load_id_family(root, "alpha_car")


# ── the real Skoda demo recordings ───────────────────────────────────────────

SKODA_MF4 = REPO / "assets" / "Train" / "Skoda Enyaq"


def test_all_skoda_demo_files_are_protected() -> None:
    assert {p.as_posix() for p in cp.PROTECTED_EVALUATION_FILES} == \
        {f"Skoda Enyaq/file_{n}.csv" for n in range(12, 19)}


@pytest.mark.skipif(not SKODA_MF4.is_dir() or not (REPO / "assets" / "Skoda Enyaq" / "file_16.csv").is_file(),
                    reason="Skoda recordings not present")
def test_every_skoda_mf4_is_protected_by_a_demo_file() -> None:
    """Each Skoda training MF4 holds one of file_12..18, so none can be trained on."""
    protected = cp._protected_recordings(REPO / "assets", cp.PROTECTED_EVALUATION_FILES)
    mf4s = sorted(p for p in SKODA_MF4.rglob("*") if p.suffix.lower() == ".mf4")
    assert len(mf4s) == 7
    covered = {}
    for path in mf4s:
        frames = rec.load_recording(rec.Recording("skoda_enyaq", path, "mf4"))
        reason = cp.protection_reason(rec.content_hash(frames), rec.traffic_rows(frames), protected)
        assert reason, f"{path.name} contains no protected demo file"
        covered[path.relative_to(SKODA_MF4).as_posix()] = reason
    assert "identical to protected evaluation file Skoda Enyaq/file_16.csv" in covered[
        "LOG/F461BFAC/00000038/00000001-631DB27A.MF4"]



# ── sparse / unseen labelling (clean-2-002 fix) ──────────────────────────────

def test_seen_id_without_feature_rows_is_sparse_in_manifest(staged) -> None:
    m = json.loads((staged / "alpha_car" / "manifest.json").read_text())
    assert m["sparse_ids"]["0x7E0"] == {"rows": 0, "recordings": 1}


def test_manifest_and_runtime_agree_on_every_training_id(assets, staged) -> None:
    """Every CAN ID in the training frames is in exactly one manifest list, and never unseen at runtime."""
    from backend.ml.runtime.model_manifest import SCORED, SPARSE_ID, UNSEEN_ID

    fam = load_id_family(staged, "alpha_car")
    m = fam.manifest
    listed = [set(m["id_models"]), set(m["sparse_ids"]), set(m["unmodelled_ids"])]
    seen = set()
    for r in m["training_corpus"]["recordings"]:
        frames = rec.load_recording(rec.Recording("alpha_car", assets / r["path"], "candump_ts"))
        seen |= {f"0x{int(c):X}" for c in frames["can_id"].unique()}
    assert seen == set().union(*listed)
    assert sum(len(s) for s in listed) == len(seen)                     # no ID in two lists
    for key in seen:
        status = fam.status(int(key, 16))
        assert status != UNSEEN_ID
        assert status == (SCORED if key in m["id_models"] else SPARSE_ID if key in m["sparse_ids"] else status)
    assert fam.status(0x555) == UNSEEN_ID


def test_rare_seen_id_is_reported_sparse_offline_and_live(staged) -> None:
    from backend.ml.runtime.realtime_engine import CanFrame, RealtimeEngine
    from backend.ml.runtime.vehicle_scoring import score_frames

    frames = _with_rare(_traffic(3, 21))
    frames = pd.concat([frames, frames.iloc[-12:].assign(can_id=RARE_ID)]).reset_index(drop=True)
    frames["timestamp"] = np.arange(len(frames)) * 0.001               # chronological, rare ID >= 11 frames
    scored = score_frames(frames, "alpha_car", model_root=staged)
    rare = scored["can_id"] == RARE_ID
    reasons = set(scored.loc[rare, "state_resolution"].str.split(":").str[0])
    assert reasons == {"warmup", "sparse_id"}
    engine = RealtimeEngine(vehicle_id="alpha_car", model_root=staged)
    states = [engine.process_frame(CanFrame(r.timestamp, int(r.can_id),
                                            tuple(int(getattr(r, f"b{i}")) for i in range(8))))["vehicle_state"]
              for r in frames.itertuples(index=False)]
    assert {s for s, c in zip(states, frames["can_id"]) if c == RARE_ID} == {"warmup", "sparse_id"}


# ── validation status ────────────────────────────────────────────────────────

def test_validation_status_recorded(staged) -> None:
    alpha = json.loads((staged / "alpha_car" / "manifest.json").read_text())["validation"]
    beta = json.loads((staged / "beta_car" / "manifest.json").read_text())["validation"]
    assert alpha["status"] == "holdout_evaluated" and alpha["has_holdout"] is True
    assert beta["status"] == "unvalidated_no_holdout" and beta["has_holdout"] is False
    assert "not evidence of generalisation" in beta["reason"]


def test_held_back_status_for_policy_families() -> None:
    assert cp.validation_status("mg_zs_ev", True)["status"] == "held_back"
    assert cp.validation_status("tesla", False)["status"] == "unvalidated_no_holdout"
    assert cp.validation_status("kia_ev6", True)["status"] == "holdout_evaluated"


@pytest.mark.parametrize("status", ["unvalidated_no_holdout", "validated", "held_back"])
def test_inconsistent_validation_status_fails(staged, tmp_path, status) -> None:
    root = _copy_family(staged, tmp_path)
    _edit(root, lambda m: m.__setitem__("validation", {"status": status, "reason": ""}))
    with pytest.raises(ManifestError, match="validation"):
        load_id_family(root, "alpha_car")


def test_held_back_family_is_never_promoted(staged, tmp_path) -> None:
    import shutil
    ver = tmp_path / "staging" / "v"
    shutil.copytree(staged, ver)
    p = ver / "gamma_car" / "manifest.json"
    m = json.loads(p.read_text())
    m["validation"] = {"status": "held_back", "reason": "test", "has_holdout": True}
    p.write_text(json.dumps(m))
    prod = tmp_path / "models"
    prod.mkdir()
    with pytest.raises(mp.PromotionError, match="held back"):
        mp.promote(ver, prod, tmp_path / "archive", families=["gamma_car"])
    assert not any(prod.iterdir())
    record = mp.promote(ver, prod, tmp_path / "archive")
    assert "gamma_car" not in record["families"] and record["held_back"] == ["gamma_car"]
    assert not (prod / "gamma_car").exists()
