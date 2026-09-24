"""
clean_pipeline.py
─────────────────
The clean model generator: per vehicle family, one anomaly model per CAN
identifier (manifest schema 3), built from recordings whose timing can be
established, over canonical features, written only to
``assets/models_staging/<version>/`` and never to ``assets/models``.

    python -m backend.ml.training.clean_pipeline plan  [--report PATH]
    python -m backend.ml.training.clean_pipeline train --version VERSION
    python -m backend.ml.training.clean_pipeline validate --version VERSION
    python -m backend.ml.training.clean_pipeline promote  --version VERSION [--family F ...]

``plan`` loads and checks every recording and prints the split; it fits
nothing. ``train`` repeats the plan, then fits. ``promote`` validates a staged
version and swaps it into production (model_promotion.py).

What it deliberately does not do, and why:

* no state classifier, and no pooling of identifiers - each CAN ID with
  enough training rows gets its own IsolationForest; the rest are reported
  as sparse, unmodelled or unseen, never scored by another ID's model;
* no per-CAN-ID normalisation against the capture being scored - the model
  learns the vehicle's normal feature space as it is;
* no timestamp repair - a recording whose timing is implausible in its
  format's declared unit is excluded (recordings.py);
* no random row sampling - a frame cap keeps a contiguous block;
* no row-level split - holdout is whole recordings, and a recording identical
  to a protected evaluation file is never trained on;
* no feature a live stream cannot compute - features come from
  backend.ml.features.canonical, which the live engine and offline analysis
  also use.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as _dt
import hashlib
import io
import json
import platform
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from backend.ml.features import canonical
from backend.ml.training import recordings as rec_mod
from backend.ml.training.recordings import Recording

PIPELINE_NAME = "backend.ml.training.clean_pipeline"
PIPELINE_VERSION = "clean-2"

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ASSETS_ROOT = PROJECT_ROOT / "assets"

# ── corpus definition ────────────────────────────────────────────────────────
# Paths relative to the assets root. Nothing outside these is read.
KAGGLE_NORMAL = Path("archive/normal_run_data.txt")          # HCRL normal run
EV_LOGS_ROOT = Path("EV-CANlogs-main")
ROAD_AMBIENT = Path("road/road/ambient")
CAR_HACKING_ROOT = Path("9) Car-Hacking Dataset")
MF4_TRAIN_ROOT = Path("Train")

ROAD_FRAME_CAP = 150_000                                     # contiguous prefix per ROAD file

#: Recordings used to evaluate the app. A recording whose traffic is identical
#: to one of these, or contains one as a contiguous slice, is moved to holdout
#: and never fitted on. The Skoda demo files are exports of the Skoda MF4
#: recordings: file_16 is 00000038 in full; file_12/13/14/15/17/18 are the
#: opening frames of 00000032/35/36/37/39-1/39-2.
PROTECTED_EVALUATION_FILES = tuple(Path(f"Skoda Enyaq/file_{n}.csv") for n in range(12, 19))

#: Families not trained at all, whatever their recordings. Their recordings stay
#: in the plan, marked excluded with this reason.
EXCLUDED_FAMILIES = {
    "nissan_leaf": "mixes a 62 kWh SavvyCAN recording with ZE0 30 kWh BusMon recordings that share its "
                   "CAN IDs (clean-1-001 holdout: 100% flagged); a BusMon-only family has no CAN ID with "
                   "enough rows and a SavvyCAN-only family has no holdout",
}

EXCLUDED_BY_POLICY = {
    # Car-Hacking 'R' frames were captured while the attacks ran on the bus.
    **{(CAR_HACKING_ROOT / n).as_posix(): "attack-session capture; normal-flagged frames recorded during an attack "
                                  "(kept for attack validation, not normal training)"
       for n in ("DoS_dataset.csv", "Fuzzy_dataset.csv", "RPM_dataset.csv", "gear_dataset.csv")},
    (ROAD_AMBIENT / "ambient_dyno_drive_benign_anomaly.log").as_posix():
        "labelled as containing a benign anomaly; not a clean normal baseline",
}

# ── model definition ─────────────────────────────────────────────────────────
# clean-2: one IsolationForest per CAN identifier (manifest schema 3). The
# forest parameters are those of clean-1; the scaler is gone (IsolationForest
# splits are invariant to per-feature linear rescaling) and the threshold is
# calibrated per identifier (model_manifest.calibrate_threshold).
MIN_TRAIN_ROWS = 2000              # a family needs at least this many ready rows
MIN_ID_ROWS = 1000                 # an identifier needs this many for its own model:
                                   # k = floor(0.02 x 1000) = 20 training rows lie below its threshold
TARGET_CONTAMINATION = 0.02
RANDOM_SEED = 42
IFOREST_PARAMS = {"n_estimators": 200, "max_samples": "auto", "contamination": "auto",
                  "random_state": RANDOM_SEED, "n_jobs": 1}
MODEL_COMPRESSION = 3              # joblib zlib level for models.joblib


class LeakageError(RuntimeError):
    pass


# ── plan ─────────────────────────────────────────────────────────────────────

@dataclass
class RecordingInfo:
    vehicle: str
    path: str                  # relative to the assets root, forward slashes
    fmt: str
    status: str                # "train" | "holdout" | "excluded"
    reason: str = ""
    file_sha256: str = ""
    content_sha256: str = ""
    frames: int = 0
    frame_cap: int | None = None
    duration_s: float = 0.0
    can_ids: int = 0


@dataclass
class TrainingPlan:
    assets_root: str
    created_at: str
    recordings: list[RecordingInfo] = field(default_factory=list)
    families: dict[str, dict] = field(default_factory=dict)
    protected: list[dict] = field(default_factory=list)
    corpus_fingerprint: str = ""

    def by_status(self, status: str, vehicle: str | None = None) -> list[RecordingInfo]:
        return [r for r in self.recordings
                if r.status == status and (vehicle is None or r.vehicle == vehicle)]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["pipeline"] = {"name": PIPELINE_NAME, "version": PIPELINE_VERSION,
                         "feature_pipeline": canonical.FEATURE_VERSION}
        return d


def _rel(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _vehicle(path: Path, root: Path) -> str:
    return path.relative_to(root).parts[0].strip().lower().replace(" ", "_")


def discover(assets_root: Path) -> list[Recording]:
    """Every candidate recording, in a fixed order."""
    found: list[Recording] = []
    kaggle = assets_root / KAGGLE_NORMAL
    if kaggle.is_file():
        found.append(Recording("kaggle_normal", kaggle, rec_mod.detect_format(kaggle)))
    ev = assets_root / EV_LOGS_ROOT
    if ev.is_dir():
        paths = sorted({p for ext in ("*.csv", "*.log", "*.asc", "*.txt") for p in ev.rglob(ext) if p.is_file()},
                       key=lambda p: p.as_posix())
        found += [Recording(_vehicle(p, ev), p, rec_mod.detect_format(p)) for p in paths]
    road = assets_root / ROAD_AMBIENT
    if road.is_dir():
        found += [Recording("road_ambient", p, rec_mod.detect_format(p), ROAD_FRAME_CAP)
                  for p in sorted(road.glob("*.log"))]
    chd = assets_root / CAR_HACKING_ROOT
    if chd.is_dir():
        found += [Recording("car_hacking", p, "car_hacking_csv") for p in sorted(chd.glob("*.csv"))]
    mf4 = assets_root / MF4_TRAIN_ROOT
    if mf4.is_dir():
        found += [Recording(_vehicle(p, mf4), p, "mf4")
                  for p in sorted(mf4.rglob("*"), key=lambda p: p.as_posix()) if p.suffix.lower() == ".mf4"]
    return found


def _protected_recordings(assets_root: Path, files) -> dict[str, tuple[str, np.ndarray]]:
    """content_hash -> (protected file, traffic rows), read with the app's own offline parser."""
    from backend.offline.session_analyzer import _load_csv

    out: dict[str, tuple[str, np.ndarray]] = {}
    for rel in files:
        rel = Path(rel)
        path = assets_root / rel
        if not path.is_file():
            # A protection that silently disappears would let the recording into training.
            raise FileNotFoundError(f"protected evaluation file missing: {path}")
        frames = rec_mod._frame([[t, c, *rec_mod._pad(list(p))] for t, c, p in _load_csv(path)])
        out[rec_mod.content_hash(frames)] = (rel.as_posix(), rec_mod.traffic_rows(frames))
    return out


def protection_reason(content_sha256: str, rows: np.ndarray,
                      protected: dict[str, tuple[str, np.ndarray]]) -> str:
    """Why a recording may never be trained on, or "" when nothing protects it."""
    reasons = []
    for h, (ppath, prows) in protected.items():
        if h == content_sha256:
            reasons.append(f"identical to protected evaluation file {ppath}")
        elif rec_mod.contains(rows, prows):
            reasons.append(f"contains protected evaluation file {ppath}")
    return "; ".join(reasons)


def build_plan(assets_root: Path = ASSETS_ROOT, log=print,
               protected_files=PROTECTED_EVALUATION_FILES) -> TrainingPlan:
    """Load and check every recording and decide train / holdout / excluded.

    Fits nothing. Every recording that is not used appears with its reason.
    """
    assets_root = Path(assets_root)
    plan = TrainingPlan(str(assets_root), _now())
    protected = _protected_recordings(assets_root, protected_files)
    plan.protected = [{"path": p, "content_sha256": h} for h, (p, _) in protected.items()]
    forced: dict[str, str] = {}          # recording path -> why it may never be trained on

    accepted: list[RecordingInfo] = []
    seen_content: dict[str, str] = {}
    for r in discover(assets_root):
        info = RecordingInfo(r.vehicle, _rel(r.path, assets_root), r.fmt, "excluded", frame_cap=r.frame_cap)
        plan.recordings.append(info)
        policy = EXCLUDED_BY_POLICY.get(r.path.relative_to(assets_root).as_posix())
        if policy:
            info.reason = policy
            continue
        if r.fmt not in rec_mod.LOADABLE_FORMATS:
            info.reason = rec_mod.UNITLESS_FORMATS.get(r.fmt, f"unrecognised format ({r.fmt})")
            continue
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                frames = rec_mod.load_recording(r)
        except Exception as exc:  # the file could not be read as its format: record why
            info.reason = f"load failed: {type(exc).__name__}: {exc}"
            continue
        info.frames = int(len(frames))
        info.file_sha256 = rec_mod.file_sha256(r.path)
        if len(frames):
            info.duration_s = float(frames["timestamp"].max() - frames["timestamp"].min())
            info.can_ids = int(frames["can_id"].nunique())
        problems = rec_mod.timestamp_problems(frames)
        if problems:
            info.reason = "timestamps: " + "; ".join(problems)
            continue
        info.content_sha256 = rec_mod.content_hash(frames)
        if info.content_sha256 in seen_content:
            info.reason = f"identical traffic to {seen_content[info.content_sha256]}"
            continue
        seen_content[info.content_sha256] = info.path
        reason = protection_reason(info.content_sha256, rec_mod.traffic_rows(frames), protected)
        if reason:
            forced[info.path] = reason
        accepted.append(info)
        log(f"  ok  {info.vehicle:<22} {info.frames:>9,}  {info.path}")

    # Recording-level split, per vehicle.
    for vehicle in sorted({a.vehicle for a in accepted}):
        recs = sorted((a for a in accepted if a.vehicle == vehicle), key=lambda a: a.path)
        held = [a for a in recs if a.path in forced]
        for a in held:
            a.status, a.reason = "holdout", forced[a.path]
        rest = [a for a in recs if a not in held]
        if not held and len(rest) >= 2:
            rest[-1].status, rest[-1].reason = "holdout", "last recording by path (recording-level holdout)"
            rest = rest[:-1]
        for a in rest:
            a.status, a.reason = "train", ""
        train_frames = sum(a.frames for a in rest)
        holdout = [a for a in recs if a.status == "holdout"]
        fam = {"training_recordings": len(rest), "training_frames": train_frames,
               "holdout_recordings": len(holdout), "holdout_frames": sum(a.frames for a in holdout),
               "holdout": "none (single recording)" if not holdout else "yes"}
        if not rest:
            fam["status"] = "excluded"
            fam["reason"] = "no training recording remains after holdout"
        elif train_frames < MIN_TRAIN_ROWS:
            fam["status"] = "excluded"
            fam["reason"] = f"{train_frames} training frames (minimum {MIN_TRAIN_ROWS})"
            for a in rest:
                a.status, a.reason = "excluded", "family has insufficient training data"
        else:
            fam["status"] = "planned"
        if vehicle in EXCLUDED_FAMILIES:
            fam["status"], fam["reason"] = "excluded", EXCLUDED_FAMILIES[vehicle]
            for a in recs:
                if a.status in ("train", "holdout"):
                    a.status, a.reason = "excluded", f"family excluded by policy: {EXCLUDED_FAMILIES[vehicle]}"
        plan.families[vehicle] = fam

    check_no_leakage(plan)
    plan.corpus_fingerprint = corpus_fingerprint(plan.by_status("train"))
    return plan


def check_no_leakage(plan: TrainingPlan) -> None:
    """No training recording may share traffic with a holdout or protected recording."""
    train = {r.content_sha256: r.path for r in plan.by_status("train")}
    others = {r.content_sha256: r.path for r in plan.by_status("holdout")}
    others.update({p["content_sha256"]: p["path"] for p in plan.protected})
    leaked = sorted(set(train) & set(others))
    if leaked:
        pairs = [f"{train[h]} == {others[h]}" for h in leaked]
        raise LeakageError("training recordings share traffic with holdout/protected recordings: " + "; ".join(pairs))


def corpus_fingerprint(recs: list[RecordingInfo]) -> str:
    lines = sorted(f"{r.path}\t{r.file_sha256}\t{r.content_sha256}\t{r.frames}\t{r.frame_cap}" for r in recs)
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


# ── features and validation ──────────────────────────────────────────────────

def recording_features(info: RecordingInfo, assets_root: Path) -> tuple[np.ndarray, np.ndarray]:
    """Canonical features and CAN IDs of one recording's ready frames, re-verified against the plan.

    Each recording starts from an empty feature state, so no window spans two
    recordings.
    """
    rec = Recording(info.vehicle, Path(assets_root) / info.path, info.fmt, info.frame_cap)
    with contextlib.redirect_stdout(io.StringIO()):
        frames = rec_mod.load_recording(rec)
    if rec_mod.content_hash(frames) != info.content_sha256:
        raise RuntimeError(f"{info.path} changed since it was planned")
    frames = rec_mod.chronological(frames)
    x, ready = canonical.compute_features_frame(frames)
    return x[ready], frames["can_id"].to_numpy(dtype=np.int64)[ready]


def varying_features(x: np.ndarray) -> tuple[list[str], dict[str, float]]:
    """Canonical features that vary for one identifier; constant ones with their value.

    A feature is dropped only when every training row has the same value: an
    IsolationForest cannot split on it, so keeping it would change nothing.
    """
    if not np.isfinite(x).all():
        raise ValueError(f"{int((~np.isfinite(x)).sum())} feature values are NaN or Inf")
    kept: list[str] = []
    constant: dict[str, float] = {}
    for i, name in enumerate(canonical.FEATURES):
        col = x[:, i]
        if col.max() > col.min():
            kept.append(name)
        else:
            constant[name] = float(col[0])
    return kept, constant


def fit_id_models(x: np.ndarray, ids: np.ndarray, id_recordings: np.ndarray) -> tuple[dict, dict, dict, dict]:
    """One IsolationForest per identifier with enough rows; the rest classified.

    Returns (models, id_models, sparse_ids, unmodelled_ids) keyed by "0x..." with
    the manifest entries for each.
    """
    from sklearn.ensemble import IsolationForest

    from backend.ml.runtime.model_manifest import calibrate_threshold, can_id_key

    models, id_models, sparse, unmodelled = {}, {}, {}, {}
    for cid in np.unique(ids):
        key = can_id_key(int(cid))
        rows = np.flatnonzero(ids == cid)
        n_rec = int(len(np.unique(id_recordings[rows])))
        if len(rows) < MIN_ID_ROWS:
            sparse[key] = {"rows": int(len(rows)), "recordings": n_rec}
            continue
        xi = x[rows]
        kept, constant = varying_features(xi)
        if not kept:
            unmodelled[key] = {"rows": int(len(rows)), "recordings": n_rec,
                               "reason": "no canonical feature varies in training", "constant": constant}
            continue
        index = [canonical.FEATURES.index(f) for f in kept]
        xf = np.ascontiguousarray(xi[:, index])
        model = IsolationForest(**IFOREST_PARAMS).fit(xf)
        cal = calibrate_threshold(model.score_samples(xf), TARGET_CONTAMINATION)
        if not cal["median"] > cal["threshold"]:
            unmodelled[key] = {"rows": int(len(rows)), "recordings": n_rec,
                               "reason": "training scores do not separate (median equals threshold)"}
            continue
        models[key] = model
        id_models[key] = {"features": kept, "constant_features": constant, "recordings": n_rec,
                          **{k: cal[k] for k in ("threshold", "median", "rows", "k", "flagged_count",
                                                 "ties_at_threshold")}}
    return models, id_models, sparse, unmodelled


# ── training (writes only to staging) ────────────────────────────────────────

def staging_root(assets_root: Path = ASSETS_ROOT) -> Path:
    return Path(assets_root) / "models_staging"


def production_root(assets_root: Path = ASSETS_ROOT) -> Path:
    return Path(assets_root) / "models"


def _check_version(version: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", version or ""):
        raise ValueError(f"invalid version {version!r}: letters, digits, '.', '_' and '-' only")


def _output_dir(assets_root: Path, version: str, out_root: Path | None) -> Path:
    _check_version(version)
    root = Path(out_root) if out_root is not None else staging_root(assets_root)
    out = (root / version).resolve()
    prod = production_root(assets_root).resolve()
    if out == prod or prod in out.parents:
        raise ValueError(f"refusing to write inside the production model root {prod}")
    if out.exists():
        raise FileExistsError(f"{out} already exists; a staged version is never overwritten")
    return out


def train(version: str, assets_root: Path = ASSETS_ROOT, out_root: Path | None = None,
          plan: TrainingPlan | None = None, log=print) -> Path:
    """Fit per-CAN-ID models for every planned family into ``<staging>/<version>/``."""
    import joblib
    import sklearn

    from backend.ml.runtime.model_manifest import (
        CANONICAL_PIPELINE_NAME, ID_SCHEMA_VERSION, MANIFEST_NAME, SCORED, file_sha256, load_id_family,
    )

    assets_root = Path(assets_root)
    out = _output_dir(assets_root, version, out_root)
    plan = plan or build_plan(assets_root, log=log)
    out.mkdir(parents=True)
    git = _git_state()
    env = {"python": platform.python_version(), "sklearn": sklearn.__version__,
           "numpy": np.__version__, "pandas": pd.__version__}
    results: dict[str, dict] = {}

    for family, fam in plan.families.items():
        if fam["status"] != "planned":
            results[family] = {"status": "excluded", "reason": fam["reason"]}
            continue
        train_recs = plan.by_status("train", family)
        hold_recs = plan.by_status("holdout", family)
        try:
            parts = [recording_features(r, assets_root) for r in train_recs]
            x = np.vstack([p[0] for p in parts])
            ids = np.concatenate([p[1] for p in parts])
            rec_of = np.concatenate([np.full(len(p[1]), i) for i, p in enumerate(parts)])
            if len(x) < MIN_TRAIN_ROWS:
                raise ValueError(f"{len(x)} feature rows after warm-up (minimum {MIN_TRAIN_ROWS})")
            models, id_models, sparse, unmodelled = fit_id_models(x, ids, rec_of)
            if not id_models:
                raise ValueError(f"no CAN ID has {MIN_ID_ROWS} training rows with a varying feature")
        except Exception as exc:
            results[family] = {"status": "failed", "reason": f"{type(exc).__name__}: {exc}"}
            log(f"  FAILED {family}: {exc}")
            continue

        fam_dir = out / family
        fam_dir.mkdir()
        joblib.dump(models, fam_dir / "models.joblib", compress=MODEL_COMPRESSION)
        corpus = {"fingerprint": corpus_fingerprint(train_recs),
                  "recordings": [_rec_entry(r) for r in train_recs]}
        holdout = {"recordings": [_rec_entry(r) for r in hold_recs]}
        calibration = {"method": "empirical_quantile_strict", "target_contamination": TARGET_CONTAMINATION,
                       "definition": "threshold = (k+1)-th smallest training score_samples value, "
                                     "k = floor(target_contamination x rows); flagged iff score < threshold; "
                                     "ties at the threshold are not flagged"}
        _write_json(fam_dir / "features.json", {"feature_pipeline": canonical.FEATURE_VERSION, "window": canonical.WINDOW,
                                                "per_can_id": {k: {"features": v["features"],
                                                                   "constant_features": v["constant_features"]}
                                                               for k, v in id_models.items()}})
        _write_json(fam_dir / "thresholds.json", {"calibration": calibration,
                                                  "per_can_id": {k: {c: v[c] for c in ("threshold", "median", "rows", "k",
                                                                                       "flagged_count", "ties_at_threshold")}
                                                                 for k, v in id_models.items()}})
        _write_json(fam_dir / "corpus.json", {"training": corpus, "holdout": holdout})
        manifest = {
            "schema_version": ID_SCHEMA_VERSION,
            "model_family": family,
            "model_version": version,
            "created_at": _now(),
            "training_pipeline": {"name": PIPELINE_NAME, "version": PIPELINE_VERSION, **git},
            "feature_pipeline": {"name": CANONICAL_PIPELINE_NAME, "version": canonical.FEATURE_VERSION,
                                 "window": canonical.WINDOW},
            "model_type": "isolation_forest_per_can_id",
            "model_params": {"model": "IsolationForest", "scaler": None, **IFOREST_PARAMS},
            "calibration": calibration,
            "min_id_rows": MIN_ID_ROWS,
            "models_file": {"path": "models.joblib", "sha256": file_sha256(fam_dir / "models.joblib")},
            "id_models": id_models,
            "sparse_ids": sparse,
            "unmodelled_ids": unmodelled,
            "training_corpus": corpus,
            "holdout": holdout,
            "environment": env,
        }
        _write_json(fam_dir / MANIFEST_NAME, manifest)
        bundle = load_id_family(out, family)             # the staged family must validate as written

        # Holdout is scored, never fitted or calibrated on.
        evaluation = []
        for r in hold_recs:
            xh, idh = recording_features(r, assets_root)
            _, flagged, status = bundle.score_rows(xh, idh)
            scored = status == SCORED
            evaluation.append({
                "path": r.path, "rows": int(len(idh)),
                "status_rows": {s: int((status == s).sum()) for s in sorted(set(status.tolist()))},
                "scored_rows": int(scored.sum()), "flagged": int(flagged.sum()),
                "flagged_share_of_scored": float(flagged[scored].mean()) if scored.any() else None,
            })
        train_rows_scored = sum(v["rows"] for v in id_models.values())
        results[family] = {
            "status": "staged", "training_rows": int(len(x)), "can_ids": int(len(np.unique(ids))),
            "id_models": len(id_models), "sparse_ids": len(sparse), "unmodelled_ids": len(unmodelled),
            "training_rows_modelled": int(train_rows_scored),
            "training_flagged": int(sum(v["flagged_count"] for v in id_models.values())),
            "holdout_evaluation": evaluation,
        }
        log(f"  staged {family}: {len(id_models)} CAN-ID models, {len(sparse)} sparse, {len(unmodelled)} unmodelled")

    _write_json(out / "training_report.json", {"version": version, "plan": plan.to_dict(), "results": results,
                                               "environment": env, "training_pipeline": git})
    _write_json(out / "corpus.json", {"fingerprint": plan.corpus_fingerprint,
                                      "recordings": [asdict(r) for r in plan.recordings]})
    _write_json(out / "pipeline.json", {"name": PIPELINE_NAME, "version": PIPELINE_VERSION,
                                        "feature_pipeline": canonical.FEATURE_VERSION,
                                        "window": canonical.WINDOW, "features": list(canonical.FEATURES),
                                        "model_params": IFOREST_PARAMS, "min_id_rows": MIN_ID_ROWS,
                                        "target_contamination": TARGET_CONTAMINATION,
                                        "min_train_rows": MIN_TRAIN_ROWS, **git})
    return out


def _rec_entry(r: RecordingInfo) -> dict:
    return {"path": r.path, "sha256": r.file_sha256, "content_sha256": r.content_sha256,
            "frames": r.frames, "frame_cap": r.frame_cap}


def _write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def _git_state() -> dict:
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, capture_output=True,
                                text=True, check=True).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain", "--", "backend"], cwd=PROJECT_ROOT,
                                    capture_output=True, text=True, check=True).stdout.strip())
        return {"git_commit": commit, "git_dirty": dirty}
    except (OSError, subprocess.CalledProcessError):
        return {"git_commit": "", "git_dirty": None}


# ── report ───────────────────────────────────────────────────────────────────

def format_plan(plan: TrainingPlan) -> str:
    lines = [f"corpus fingerprint {plan.corpus_fingerprint}", ""]
    lines.append(f"{'vehicle':<24}{'train rec':>10}{'train frames':>14}{'holdout rec':>12}{'holdout frames':>16}  status")
    for v, f in sorted(plan.families.items()):
        lines.append(f"{v:<24}{f['training_recordings']:>10}{f['training_frames']:>14,}"
                     f"{f['holdout_recordings']:>12}{f['holdout_frames']:>16,}  "
                     f"{f['status']}{' - ' + f['reason'] if f.get('reason') else ''}"
                     f"{'' if f['holdout_recordings'] else '  [no holdout]'}")
    lines += ["", "holdout recordings:"]
    lines += [f"  {r.vehicle:<22} {r.frames:>9,}  {r.path}  ({r.reason})" for r in plan.by_status("holdout")]
    lines += ["", "excluded recordings:"]
    lines += [f"  {r.vehicle:<22} {r.path}\n      {r.reason}" for r in plan.by_status("excluded")]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="clean_pipeline")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_plan = sub.add_parser("plan", help="check the corpus and print the split; fits nothing")
    p_plan.add_argument("--report", type=Path)
    p_train = sub.add_parser("train", help="fit into assets/models_staging/<version>/")
    p_train.add_argument("--version", required=True)
    p_val = sub.add_parser("validate", help="validate a staged version")
    p_val.add_argument("--version", required=True)
    p_pro = sub.add_parser("promote", help="validate a staged version and swap it into assets/models")
    p_pro.add_argument("--version", required=True)
    p_pro.add_argument("--family", action="append")
    args = ap.parse_args(argv)

    from backend.ml.training import model_promotion

    if args.cmd == "plan":
        plan = build_plan()
        print(format_plan(plan))
        if args.report:
            _write_json(args.report, plan.to_dict())
    elif args.cmd == "train":
        out = train(args.version)
        print(f"staged: {out}")
    elif args.cmd == "validate":
        staged = model_promotion.validate_staging(staging_root() / args.version)
        print("valid families: " + ", ".join(sorted(staged)))
    elif args.cmd == "promote":
        record = model_promotion.promote(staging_root() / args.version, production_root(),
                                         ASSETS_ROOT / "models_archive", families=args.family)
        print(json.dumps(record, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
