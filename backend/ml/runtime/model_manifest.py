"""
model_manifest.py
─────────────────
One versioned description of a trained model family, and the checks that refuse
to score with anything that does not match it.

Why this exists
---------------
A family's anomaly models are only meaningful for the state partition they were
trained on: the "driving" model was fitted to the frames one particular state
classifier called driving. Nothing recorded which classifier that was. On
22 June the classifier was retrained on different data, in a different feature
space, and overwritten in place, while the anomaly models trained against the
20 June classifier stayed. Every frame was then routed by a classifier the
models had never been paired with - and the replacement also carried a scaler
dimension with a scale of 2.2e-10, so its output was decided by one feature and
floating-point noise. Nothing failed; the numbers were simply wrong.

A manifest pins a family to the exact classifier files, feature lists, scalers,
models and thresholds it was produced with, by SHA-256. Loading validates all of
it and raises on any mismatch. Nothing here falls back: no default state, no
zero score, no missing feature read as 0.0.

Manifest (schema_version 1), stored as ``<models>/<family>/manifest.json``::

    {
      "schema_version": 1,
      "model_family": "skoda_enyaq",
      "model_version": "...",
      "created_at": "ISO-8601",
      "training_pipeline": "module@revision",
      "training_corpus": {"id": "...", "sha256": "..."},
      "sklearn_version": "1.9.0",
      "state_classifier": {
        "version": "...",
        "input_space": "training_parity" | "runtime",
        "features": [...],                         # order is the contract
        "scaler": {"path": "...", "sha256": "..."},
        "kmeans": {"path": "...", "sha256": "..."},
        "mapping": {"0": "driving", "1": "idle", "2": "parking"}
      },
      "states": {
        "driving": {"features": [...],
                    "scaler": {"path": "...", "sha256": "..."},
                    "model":  {"path": "...", "sha256": "..."},
                    "threshold": 0.157}
      },
      "unmodelled_states": ["parking"]
    }

Paths are relative to the manifest's directory. A state the classifier can
produce must appear either under ``states`` or in ``unmodelled_states``; frames
routed to an unmodelled state are reported as unresolved, never scored as zero.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
MANIFEST_NAME = "manifest.json"

#: State given to a frame whose state could not be resolved to a trained model.
UNRESOLVED = "unresolved"

#: A fitted scale below this is not a measurement of spread; it is the residue
#: of scaling a constant column, and it multiplies that feature by ~1/scale.
NEAR_ZERO_SCALE = 1e-6

INPUT_SPACES = ("training_parity", "runtime")


class ManifestError(RuntimeError):
    """The artifacts do not form one consistent, verifiable model version."""

    def __init__(self, family: str, problems: Sequence[str]):
        self.family = family
        self.problems = list(problems)
        lines = "\n  - ".join(self.problems)
        super().__init__(f"model family '{family}' failed validation:\n  - {lines}")


# ── helpers ──────────────────────────────────────────────────────────────────

def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _n_features(obj: Any) -> int | None:
    n = getattr(obj, "n_features_in_", None)
    return int(n) if n is not None else None


def _feature_names(obj: Any) -> list[str] | None:
    names = getattr(obj, "feature_names_in_", None)
    return [str(n) for n in names] if names is not None else None


def near_zero_scale_features(scaler: Any, features: Sequence[str]) -> list[str]:
    """Feature names whose fitted scale is effectively zero."""
    scale = getattr(scaler, "scale_", None)
    if scale is None:
        return []
    return [f"{features[i] if i < len(features) else f'#{i}'} (scale {float(s):.3g})"
            for i, s in enumerate(np.asarray(scale, dtype=float)) if abs(s) < NEAR_ZERO_SCALE]


# ── loaded, validated form ───────────────────────────────────────────────────

@dataclass
class StateClassifier:
    version: str
    input_space: str
    features: list[str]
    scaler: Any
    kmeans: Any
    mapping: dict[int, str]


@dataclass
class StateModel:
    features: list[str]
    scaler: Any
    model: Any
    threshold: float


@dataclass
class ValidatedBundle:
    family: str
    manifest: dict
    classifier: StateClassifier
    models: dict[str, StateModel]
    unmodelled_states: set[str] = field(default_factory=set)

    def resolve_states(self, x: np.ndarray) -> tuple[list[str], list[str]]:
        """State per row, or UNRESOLVED with the reason.

        ``x`` holds the classifier's features in manifest order. A classifier
        error, a cluster the mapping does not name, or a state with no trained
        model all yield UNRESOLVED - never a default state.
        """
        n = len(x)
        if n == 0:
            return [], []
        clf = self.classifier
        try:
            dtype = np.asarray(clf.kmeans.cluster_centers_).dtype
            z = clf.scaler.transform(np.asarray(x, dtype=np.float64))
            labels = clf.kmeans.predict(np.asarray(z, dtype=dtype))
        except Exception as exc:  # the classifier could not answer: say so for every row
            reason = f"classifier_error: {type(exc).__name__}: {exc}"
            logger.error("[MANIFEST] %s state classifier failed: %s", self.family, reason)
            return [UNRESOLVED] * n, [reason] * n

        states: list[str] = []
        reasons: list[str] = []
        for label in np.asarray(labels).tolist():
            state = clf.mapping.get(int(label))
            if state is None:
                states.append(UNRESOLVED)
                reasons.append(f"unmapped_cluster:{int(label)}")
            elif state not in self.models:
                states.append(UNRESOLVED)
                reasons.append(f"no_model_for_state:{state}")
            else:
                states.append(state)
                reasons.append("")
        return states, reasons

    def score(self, states: Sequence[str], columns: Mapping[str, Any]) -> list[float | None]:
        """Normalised 0-1 anomaly score per row; None for unresolved rows.

        Every feature a routed state's model needs must be in ``columns``; a
        missing one raises with its name.
        """
        scores: list[float | None] = [None] * len(states)
        groups: dict[str, list[int]] = {}
        for i, s in enumerate(states):
            if s != UNRESOLVED:
                groups.setdefault(s, []).append(i)

        for state in groups:
            missing = [f for f in self.models[state].features if f not in columns]
            if missing:
                raise ValueError(f"model for state '{state}' requires features that were not produced: {missing}")

        for state, idxs in groups.items():
            m = self.models[state]
            index = np.asarray(idxs)
            x = np.column_stack([np.asarray(columns[f], dtype=np.float64)[index] for f in m.features])
            raw = m.model.decision_function(m.scaler.transform(x))
            th = m.threshold
            span = max(abs(th), 0.01)
            for j, i in enumerate(idxs):
                scores[i] = float(max(0.0, min(1.0, 0.5 + (th - float(raw[j])) / (2.0 * span))))
        return scores


# ── loading and validation ───────────────────────────────────────────────────

def _resolve(base: Path, ref: Any, what: str, problems: list[str]) -> Path | None:
    if not isinstance(ref, dict) or "path" not in ref or "sha256" not in ref:
        problems.append(f"{what}: entry must give 'path' and 'sha256'")
        return None
    path = (base / ref["path"]).resolve()
    if not path.is_file():
        problems.append(f"{what}: file not found: {path}")
        return None
    actual = file_sha256(path)
    if actual != ref["sha256"]:
        problems.append(
            f"{what}: {path.name} does not match the file this family was built with "
            f"(sha256 {actual[:12]}… != manifest {str(ref['sha256'])[:12]}…)"
        )
        return None
    return path


def load_validated_bundle(model_root: Path, family: str, *, runtime_feature_order: Sequence[str] | None = None) -> ValidatedBundle:
    """Load a family and prove its parts belong together, or raise ManifestError.

    Every problem found is reported at once, not just the first.
    """
    import joblib

    family_dir = Path(model_root) / family
    manifest_path = family_dir / MANIFEST_NAME
    problems: list[str] = []

    if not manifest_path.is_file():
        raise ManifestError(family, [
            f"no {MANIFEST_NAME} in {family_dir}: these artifacts do not record which state "
            "classifier, features, scalers and thresholds they were produced with, so their "
            "consistency cannot be verified"
        ])
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(family, [f"{MANIFEST_NAME} is unreadable: {exc}"]) from exc

    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ManifestError(family, [f"unsupported schema_version {manifest.get('schema_version')!r}; expected {SCHEMA_VERSION}"])
    for key in ("model_family", "model_version", "created_at", "training_pipeline",
                "training_corpus", "state_classifier", "states"):
        if key not in manifest:
            problems.append(f"manifest is missing '{key}'")
    if manifest.get("model_family") not in (None, family):
        problems.append(f"manifest names family '{manifest.get('model_family')}', loaded as '{family}'")
    if problems:
        raise ManifestError(family, problems)

    try:
        import sklearn
        built = manifest.get("sklearn_version")
        if built and built != sklearn.__version__:
            logger.warning("[MANIFEST] %s was built with scikit-learn %s, running %s",
                           family, built, sklearn.__version__)
    except ImportError:
        pass

    # ── state classifier ────────────────────────────────────────────────────
    sc = manifest["state_classifier"]
    c_feats = list(sc.get("features") or [])
    input_space = sc.get("input_space")
    if input_space not in INPUT_SPACES:
        problems.append(f"state_classifier.input_space must be one of {INPUT_SPACES}, got {input_space!r}")
    if not c_feats:
        problems.append("state_classifier.features is empty")
    elif len(set(c_feats)) != len(c_feats):
        problems.append("state_classifier.features contains duplicates")
    if input_space == "runtime" and runtime_feature_order is not None and c_feats != list(runtime_feature_order):
        problems.append(
            "state_classifier.features do not match the runtime feature schema in name and order: "
            f"manifest {c_feats} vs runtime {list(runtime_feature_order)}"
        )

    scaler_path = _resolve(family_dir, sc.get("scaler"), "state_classifier.scaler", problems)
    kmeans_path = _resolve(family_dir, sc.get("kmeans"), "state_classifier.kmeans", problems)
    c_scaler = joblib.load(scaler_path) if scaler_path else None
    kmeans = joblib.load(kmeans_path) if kmeans_path else None

    if c_scaler is not None and c_feats:
        n = _n_features(c_scaler)
        if n is not None and n != len(c_feats):
            problems.append(f"state classifier scaler expects {n} features, manifest lists {len(c_feats)}")
        names = _feature_names(c_scaler)
        if names is not None and names != c_feats:
            problems.append(f"state classifier scaler was fitted on features {names}, manifest lists {c_feats} (name or order differs)")
        bad = near_zero_scale_features(c_scaler, c_feats)
        if bad:
            problems.append(f"state classifier scaler has near-zero scale for {bad}")
    if kmeans is not None and c_feats:
        n = _n_features(kmeans)
        if n is not None and n != len(c_feats):
            problems.append(f"state classifier KMeans expects {n} features, manifest lists {len(c_feats)}")

    raw_mapping = sc.get("mapping") or {}
    try:
        mapping = {int(k): str(v) for k, v in raw_mapping.items()}
    except (TypeError, ValueError):
        mapping = {}
        problems.append("state_classifier.mapping keys must be cluster indices")
    if kmeans is not None:
        k = int(getattr(kmeans, "n_clusters", len(mapping)))
        missing = sorted(set(range(k)) - set(mapping))
        extra = sorted(set(mapping) - set(range(k)))
        if missing:
            problems.append(f"state_classifier.mapping does not name clusters {missing}")
        if extra:
            problems.append(f"state_classifier.mapping names clusters {extra} the classifier does not have")

    # ── state models ────────────────────────────────────────────────────────
    models: dict[str, StateModel] = {}
    declared_unmodelled = set(manifest.get("unmodelled_states") or [])
    states_section = manifest.get("states") or {}
    if not states_section:
        problems.append("manifest declares no trained state models")

    for state, entry in states_section.items():
        feats = list(entry.get("features") or [])
        if not feats:
            problems.append(f"state '{state}': features list is empty")
        threshold = entry.get("threshold")
        if not isinstance(threshold, (int, float)) or isinstance(threshold, bool) or not math.isfinite(float(threshold)):
            problems.append(f"state '{state}': threshold missing or not a finite number ({threshold!r})")
        s_path = _resolve(family_dir, entry.get("scaler"), f"state '{state}' scaler", problems)
        m_path = _resolve(family_dir, entry.get("model"), f"state '{state}' model", problems)
        scaler = joblib.load(s_path) if s_path else None
        model = joblib.load(m_path) if m_path else None
        for obj, what in ((scaler, "scaler"), (model, "model")):
            if obj is None or not feats:
                continue
            n = _n_features(obj)
            if n is not None and n != len(feats):
                problems.append(f"state '{state}': {what} expects {n} features, manifest lists {len(feats)}")
            names = _feature_names(obj)
            if names is not None and names != feats:
                problems.append(f"state '{state}': {what} was fitted on {names}, manifest lists {feats}")
        if scaler is not None and feats:
            bad = near_zero_scale_features(scaler, feats)
            if bad:
                problems.append(f"state '{state}': scaler has near-zero scale for {bad}")
        if scaler is not None and model is not None and feats and isinstance(threshold, (int, float)):
            models[state] = StateModel(feats, scaler, model, float(threshold))

    overlap = declared_unmodelled & set(states_section)
    if overlap:
        problems.append(f"states {sorted(overlap)} are declared both modelled and unmodelled")
    for cluster, state in sorted(mapping.items()):
        if state not in states_section and state not in declared_unmodelled:
            problems.append(
                f"classifier routes cluster {cluster} to state '{state}', which has no model and "
                "is not declared in unmodelled_states"
            )

    if problems:
        raise ManifestError(family, problems)

    classifier = StateClassifier(str(sc.get("version", "")), str(input_space), c_feats, c_scaler, kmeans, mapping)
    return ValidatedBundle(family, manifest, classifier, models, declared_unmodelled)


# ── writing (for the atomic model-generation run) ────────────────────────────

def build_manifest(
    family_dir: Path,
    *,
    family: str,
    model_version: str,
    created_at: str,
    training_pipeline: str,
    training_corpus: Mapping[str, str],
    classifier_version: str,
    classifier_input_space: str,
    classifier_features: Sequence[str],
    classifier_scaler: Path,
    classifier_kmeans: Path,
    mapping: Mapping[int, str],
    states: Mapping[str, Mapping[str, Any]],
    unmodelled_states: Sequence[str] = (),
) -> dict:
    """Manifest for artifacts already on disk; hashes are taken from the files.

    ``states`` maps a state to ``{"features", "scaler", "model", "threshold"}``
    with ``scaler``/``model`` as paths.
    """
    family_dir = Path(family_dir)

    def ref(p: Path) -> dict:
        p = Path(p)
        return {"path": str(Path(_rel(p, family_dir))), "sha256": file_sha256(p)}

    try:
        import sklearn
        skl = sklearn.__version__
    except ImportError:
        skl = ""

    return {
        "schema_version": SCHEMA_VERSION,
        "model_family": family,
        "model_version": model_version,
        "created_at": created_at,
        "training_pipeline": training_pipeline,
        "training_corpus": dict(training_corpus),
        "sklearn_version": skl,
        "state_classifier": {
            "version": classifier_version,
            "input_space": classifier_input_space,
            "features": list(classifier_features),
            "scaler": ref(classifier_scaler),
            "kmeans": ref(classifier_kmeans),
            "mapping": {str(k): v for k, v in mapping.items()},
        },
        "states": {
            s: {
                "features": list(e["features"]),
                "scaler": ref(e["scaler"]),
                "model": ref(e["model"]),
                "threshold": float(e["threshold"]),
            }
            for s, e in states.items()
        },
        "unmodelled_states": list(unmodelled_states),
    }


def write_manifest(family_dir: Path, manifest: dict) -> Path:
    path = Path(family_dir) / MANIFEST_NAME
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path


def _rel(path: Path, base: Path) -> str:
    import os
    return os.path.relpath(Path(path).resolve(), Path(base).resolve())


# ── audit of artifacts that predate manifests ────────────────────────────────

def audit_unmanifested(model_root: Path, family: str, classifier_features: Sequence[str]) -> list[str]:
    """Every structural check that can be made without a manifest.

    For the artifacts produced before manifests existed. It cannot establish
    that the classifier and the models belong together - only a manifest can -
    so the first finding is always that; the rest are the defects detectable
    from the files themselves.
    """
    import joblib

    root = Path(model_root)
    fam = root / family
    found: list[str] = []
    if not (fam / MANIFEST_NAME).is_file():
        found.append("no manifest: the state classifier these models were trained against is not recorded")

    kpath, spath, mpath = root / "kmeans_state_model.joblib", root / "state_scaler.joblib", root / "state_mapping.json"
    kmeans = joblib.load(kpath) if kpath.is_file() else None
    scaler = joblib.load(spath) if spath.is_file() else None
    mapping = {int(k): v for k, v in json.loads(mpath.read_text()).items()} if mpath.is_file() else {}
    if kmeans is None or scaler is None or not mapping:
        found.append("state classifier artifacts missing (kmeans, scaler or mapping)")
    else:
        for obj, what in ((scaler, "scaler"), (kmeans, "KMeans")):
            n = _n_features(obj)
            if n is not None and n != len(classifier_features):
                found.append(f"state classifier {what} expects {n} features, runtime supplies {len(classifier_features)}")
        bad = near_zero_scale_features(scaler, classifier_features)
        if bad:
            found.append(f"state classifier scaler has near-zero scale for {bad}")
        k = int(getattr(kmeans, "n_clusters", 0))
        if set(mapping) != set(range(k)):
            found.append(f"state mapping covers clusters {sorted(mapping)}, classifier has {k}")

    feats_path, th_path = fam / "feature_sets.json", fam / "thresholds.json"
    feature_sets = json.loads(feats_path.read_text()) if feats_path.is_file() else {}
    thresholds = json.loads(th_path.read_text()) if th_path.is_file() else {}
    if not thresholds:
        found.append("no trained state models (thresholds.json empty or missing)")
    for state, th in thresholds.items():
        feats = feature_sets.get(state) or []
        m, s = fam / f"model_{state}.joblib", fam / f"scaler_{state}.joblib"
        if not feats:
            found.append(f"state '{state}': no feature list")
        if not (m.is_file() and s.is_file()):
            found.append(f"state '{state}': model or scaler file missing")
            continue
        sc_obj, md_obj = joblib.load(s), joblib.load(m)
        for obj, what in ((sc_obj, "scaler"), (md_obj, "model")):
            n = _n_features(obj)
            if n is not None and feats and n != len(feats):
                found.append(f"state '{state}': {what} expects {n} features, feature list has {len(feats)}")
        bad = near_zero_scale_features(sc_obj, feats)
        if bad:
            found.append(f"state '{state}': scaler has near-zero scale for {bad}")
        if not isinstance(th, (int, float)) or not math.isfinite(float(th)):
            found.append(f"state '{state}': threshold not a finite number")
    for cluster, state in sorted(mapping.items()):
        if state not in thresholds:
            found.append(f"classifier routes cluster {cluster} to '{state}', which has no model in this family")
    return found


# ══ schema 2: one model per vehicle family ═══════════════════════════════════
#
# The first clean model generation (backend.ml.training.clean_pipeline) drops
# the state classifier: each family is one RobustScaler + IsolationForest over
# canonical features (backend.ml.features.canonical). Its manifest,
# ``<family>/manifest.json``::
#
#     {
#       "schema_version": 2,
#       "model_family": "skoda_enyaq",
#       "model_version": "...", "created_at": "ISO-8601",
#       "training_pipeline": {"name": "...", "version": "...", "git_commit": "...", "git_dirty": false},
#       "feature_pipeline": {"name": "backend.ml.features.canonical",
#                            "version": "canonical-1", "window": 10},
#       "features": [...],                       # subset of canonical FEATURES, in model order
#       "dropped_features": {"name": "reason"},
#       "scaler": {"path": "scaler.joblib", "sha256": "..."},
#       "model":  {"path": "model.joblib",  "sha256": "..."},
#       "model_params": {...},
#       "threshold": {"value": -0.03, "method": "median_minus_kmad", ...},
#       "training_corpus": {"fingerprint": "...", "recordings": [{"path", "sha256", "frames"}]},
#       "holdout": {"recordings": [{"path", "sha256", "frames"}]},
#       "environment": {"python": "...", "sklearn": "...", "numpy": "...", "pandas": "..."}
#     }
#
# Everything a family needs is in its own directory; nothing is shared with
# another family, so replacing one can never change another.

FAMILY_SCHEMA_VERSION = 2
CANONICAL_PIPELINE_NAME = "backend.ml.features.canonical"


def manifest_schema(model_root: Path, family: str) -> int | None:
    """The family's manifest schema version, or None when it has no manifest."""
    path = Path(model_root) / family / MANIFEST_NAME
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("schema_version")
    except (OSError, json.JSONDecodeError):
        return -1          # present but unreadable: the loaders report it


@dataclass
class FamilyModel:
    family: str
    manifest: dict
    features: list[str]
    feature_index: list[int]      # positions of ``features`` within canonical FEATURES
    scaler: Any
    model: Any
    threshold: float

    def score(self, canonical_x: np.ndarray) -> np.ndarray:
        """Normalised 0-1 score for rows of canonical features (all FEATURES, in order)."""
        x = np.asarray(canonical_x, dtype=np.float64)[:, self.feature_index]
        if len(x) == 0:
            return np.empty(0, dtype=np.float64)
        if not np.isfinite(x).all():
            raise ValueError("canonical features contain NaN or Inf; warm-up rows must not be scored")
        raw = self.model.decision_function(self.scaler.transform(x))
        th = self.threshold
        span = max(abs(th), 0.01)
        return np.clip(0.5 + (th - raw) / (2.0 * span), 0.0, 1.0)


def load_family_model(model_root: Path, family: str) -> FamilyModel:
    """Load a schema-2 family and prove it is complete and consistent, or raise."""
    import joblib
    from backend.ml.features import canonical

    family_dir = Path(model_root) / family
    manifest_path = family_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        raise ManifestError(family, [f"no {MANIFEST_NAME} in {family_dir}"])
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(family, [f"{MANIFEST_NAME} is unreadable: {exc}"]) from exc
    if manifest.get("schema_version") != FAMILY_SCHEMA_VERSION:
        raise ManifestError(family, [
            f"schema_version {manifest.get('schema_version')!r} is not a single-model family "
            f"(expected {FAMILY_SCHEMA_VERSION})"
        ])

    problems: list[str] = []
    for key in ("model_family", "model_version", "created_at", "training_pipeline", "feature_pipeline",
                "features", "scaler", "model", "threshold", "training_corpus", "holdout"):
        if key not in manifest:
            problems.append(f"manifest is missing '{key}'")
    if problems:
        raise ManifestError(family, problems)
    if manifest["model_family"] != family:
        problems.append(f"manifest names family '{manifest['model_family']}', loaded as '{family}'")

    fp = manifest["feature_pipeline"] or {}
    if fp.get("name") != CANONICAL_PIPELINE_NAME:
        problems.append(f"feature pipeline '{fp.get('name')}' is not {CANONICAL_PIPELINE_NAME}")
    if fp.get("version") != canonical.FEATURE_VERSION:
        problems.append(
            f"model was built with feature pipeline {fp.get('version')!r}; this runtime produces "
            f"{canonical.FEATURE_VERSION!r}"
        )
    if fp.get("window") != canonical.WINDOW:
        problems.append(f"model was built with window {fp.get('window')!r}; this runtime uses {canonical.WINDOW}")

    feats = list(manifest["features"] or [])
    if not feats:
        problems.append("features list is empty")
    if len(set(feats)) != len(feats):
        problems.append("features list contains duplicates")
    not_produced = [f for f in feats if f not in canonical.FEATURES]
    if not_produced:
        problems.append(f"features {not_produced} are not produced by the canonical runtime implementation")

    s_path = _resolve(family_dir, manifest["scaler"], "scaler", problems)
    m_path = _resolve(family_dir, manifest["model"], "model", problems)
    scaler = joblib.load(s_path) if s_path else None
    model = joblib.load(m_path) if m_path else None
    for obj, what in ((scaler, "scaler"), (model, "model")):
        if obj is None or not feats:
            continue
        n = _n_features(obj)
        if n is not None and n != len(feats):
            problems.append(f"{what} expects {n} features, manifest lists {len(feats)}")
        names = _feature_names(obj)
        if names is not None and names != feats:
            problems.append(f"{what} was fitted on {names}, manifest lists {feats}")
    if scaler is not None and feats:
        bad = near_zero_scale_features(scaler, feats)
        if bad:
            problems.append(f"scaler has near-zero scale for {bad}")

    th = (manifest["threshold"] or {}).get("value")
    if not isinstance(th, (int, float)) or isinstance(th, bool) or not math.isfinite(float(th)):
        problems.append(f"threshold missing or not a finite number ({th!r})")

    train_sha = {r.get("sha256") for r in (manifest["training_corpus"] or {}).get("recordings", [])}
    hold_sha = {r.get("sha256") for r in (manifest["holdout"] or {}).get("recordings", [])}
    if not train_sha:
        problems.append("training_corpus lists no recordings")
    leaked = sorted(train_sha & hold_sha)
    if leaked:
        problems.append(f"{len(leaked)} recording(s) appear in both training and holdout")

    if problems:
        raise ManifestError(family, problems)

    index = [canonical.FEATURES.index(f) for f in feats]
    return FamilyModel(family, manifest, feats, index, scaler, model, float(th))
