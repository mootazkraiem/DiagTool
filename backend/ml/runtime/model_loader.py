"""
model_loader.py
───────────────
Loads the trained state-based IsolationForest models from assets/models/ and
provides a clean inference API for the realtime engine.

Architecture:
  - At startup, attempt to load kmeans + state_scaler (for state classification)
    and per-state IsolationForest + RobustScaler (for anomaly scoring).
  - At runtime, compute a training-compatible feature vector from the CanIdState
    deques, classify the CAN-ID's current vehicle state via KMeans, then score
    with the appropriate IsolationForest.
  - Returns a normalized anomaly score in [0, 1] — 0 = normal, 1 = extreme anomaly.
  - Falls back gracefully (returns None) when models are not loaded.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import NamedTuple

import numpy as np

logger = logging.getLogger(__name__)

# Feature order MUST match training/state_based_pipeline.py REQUIRED_FEATURES
# and backend/ml/core/feature_engineering.py FEATURE_COLS
RUNTIME_FEATURE_ORDER = [
    "time_diff",
    "rolling_std_time_diff",
    "rolling_mean_byte_diff",
    "rolling_byte_diff_std",
    "rolling_max_byte_diff",
    "msg_frequency",
    "byte_diff",
    "changed_bytes_count",
    "msg_rate",
    "rolling_var_time_diff",
    "burstiness",
    "can_id_entropy",
    "payload_entropy",
    "inter_arrival_cv",
]

# Clip bounds matching core/feature_engineering.py (before log1p)
_CLIP_BOUNDS: dict[str, tuple[float, float]] = {
    "time_diff": (0.0, 0.05),
    "rolling_std_time_diff": (0.0, 0.05),
    "rolling_mean_byte_diff": (0.0, 50.0),
    "rolling_byte_diff_std": (0.0, 50.0),
    "rolling_max_byte_diff": (0.0, 50.0),
    "msg_frequency": (0.0, 100.0),
    "byte_diff": (0.0, 50.0),
    "changed_bytes_count": (0.0, 8.0),
    "msg_rate": (0.0, 5000.0),
    "rolling_var_time_diff": (0.0, 0.1),
    "burstiness": (0.0, 100.0),
    "can_id_entropy": (0.0, 20.0),
    "payload_entropy": (0.0, 8.0),
    "inter_arrival_cv": (0.0, 50.0),
}


class _StateModel(NamedTuple):
    model: object      # IsolationForest
    scaler: object     # RobustScaler
    features: list[str]
    threshold: float


class StateModelBundle:
    """Holds all loaded models for a single model directory (general or vehicle-specific)."""

    def __init__(self, models: dict[str, _StateModel]) -> None:
        self._models = models  # state_name → _StateModel

    def score(self, state: str, feature_vec: dict[str, float]) -> float | None:
        """Score a feature vector for a given vehicle state.

        Returns anomaly severity in [0, 1]: 0 = normal, 1 = extreme anomaly.
        Returns None if no model is available for this state.
        """
        m = self._models.get(state) or self._models.get("parking")
        if m is None:
            return None
        x = np.array([[feature_vec.get(f, 0.0) for f in m.features]], dtype=np.float32)
        raw_score = float(m.model.decision_function(m.scaler.transform(x))[0])
        # decision_function: high positive = deeply normal, below threshold = anomaly
        # Normalize: map [threshold, threshold - 3*|threshold|] → [0, 1]
        th = m.threshold
        # Linear stretch so that score==threshold → 0.5, deeply anomalous → 1.0
        span = max(abs(th), 0.01)
        normalized = 0.5 + (th - raw_score) / (2.0 * span)
        return float(max(0.0, min(1.0, normalized)))

    @property
    def available_states(self) -> list[str]:
        return list(self._models.keys())


class RuntimeModelStore:
    """Top-level registry: holds kmeans state classifier + general and vehicle bundles."""

    def __init__(
        self,
        kmeans: object | None,
        state_scaler: object | None,
        state_mapping: dict[int, str],
        state_feats: list[str],
        general: StateModelBundle | None,
        vehicles: dict[str, StateModelBundle],
    ) -> None:
        self._kmeans = kmeans
        self._state_scaler = state_scaler
        self._state_mapping = state_mapping
        self._state_feats = state_feats
        self._general = general
        self._vehicles = vehicles

    def classify_state(self, feature_vec: dict[str, float]) -> str:
        """Classify vehicle state from feature vector using KMeans.

        state_scaler.transform() is required here: kmeans_state_model.joblib was fit on
        RobustScaler-scaled features (backend.ml.training.state_based_pipeline fits the
        scaler and the KMeans together), so raw feature values are a different coordinate
        space than what the cluster centers represent.
        """
        if self._kmeans is None or self._state_scaler is None:
            return "parking"
        x = np.array([[feature_vec.get(f, 0.0) for f in self._state_feats]], dtype=np.float32)
        try:
            x_scaled = self._state_scaler.transform(x)
            label = int(self._kmeans.predict(x_scaled)[0])
            return self._state_mapping.get(label, "parking")
        except Exception:
            return "parking"

    def score(self, state: str, feature_vec: dict[str, float], vehicle: str = "general") -> float | None:
        """Score a frame; prefer vehicle-specific model, fall back to general."""
        vkey = vehicle.strip().lower().replace(" ", "_")
        bundle = self._vehicles.get(vkey) or self._general
        if bundle is None:
            return None
        return bundle.score(state, feature_vec)

    @property
    def is_loaded(self) -> bool:
        return self._general is not None or bool(self._vehicles)


def _try_load_bundle(model_dir: Path) -> StateModelBundle | None:
    """Load per-state IsolationForest+scaler pairs from a model directory."""
    try:
        import joblib

        th_path = model_dir / "thresholds.json"
        fs_path = model_dir / "feature_sets.json"
        if not (th_path.exists() and fs_path.exists()):
            return None

        thresholds: dict[str, float] = json.loads(th_path.read_text(encoding="utf-8"))
        feature_sets: dict[str, list[str]] = json.loads(fs_path.read_text(encoding="utf-8"))

        state_models: dict[str, _StateModel] = {}
        for state, th in thresholds.items():
            mp = model_dir / f"model_{state}.joblib"
            sp = model_dir / f"scaler_{state}.joblib"
            if not (mp.exists() and sp.exists() and state in feature_sets):
                continue
            m = joblib.load(mp)
            s = joblib.load(sp)
            state_models[state] = _StateModel(model=m, scaler=s, features=feature_sets[state], threshold=th)

        if not state_models:
            return None
        return StateModelBundle(state_models)
    except Exception as exc:
        logger.warning("[MODEL_LOADER] Failed to load bundle from %s: %s", model_dir, exc)
        return None


def load_models(assets_root: Path | None = None) -> RuntimeModelStore:
    """Load all trained models. Safe to call even if no models exist — returns empty store."""
    if assets_root is None:
        # Infer from this file's location: backend/ml/runtime/model_loader.py → assets/
        assets_root = Path(__file__).resolve().parents[3] / "assets"

    model_root = assets_root / "models"
    if not model_root.exists():
        logger.warning("[MODEL_LOADER] Model root not found: %s", model_root)
        return RuntimeModelStore(None, None, {}, [], None, {})

    try:
        import joblib

        # State classifier (KMeans)
        kmeans = joblib.load(model_root / "kmeans_state_model.joblib") if (model_root / "kmeans_state_model.joblib").exists() else None
        state_scaler = joblib.load(model_root / "state_scaler.joblib") if (model_root / "state_scaler.joblib").exists() else None
        mapping_path = model_root / "state_mapping.json"
        state_mapping: dict[int, str] = {}
        if mapping_path.exists():
            state_mapping = {int(k): v for k, v in json.loads(mapping_path.read_text(encoding="utf-8")).items()}

        # State feature list — MUST match backend.ml.training.state_based_pipeline's
        # REQUIRED_FEATURES/STATE_FEATS exactly, since that is what kmeans_state_model.joblib
        # and state_scaler.joblib were actually fit on (14 features, RUNTIME_FEATURE_ORDER).
        #
        # This used to be read from general/feature_sets.json instead — that file stores the
        # (smaller, per-state) feature subset used by the *scoring* IsolationForest, not the
        # shared state classifier. Feeding an 11-feature vector into a KMeans model trained on
        # 14 raised `ValueError: X has 11 features, but KMeans is expecting 14 features`, which
        # classify_state()'s broad except-clause silently swallowed, always returning "parking"
        # regardless of the vehicle's actual state (confirmed: 99.93% "parking" across an entire
        # real 1-hour driving session). Using the correct, full feature list fixes this.
        state_feats: list[str] = RUNTIME_FEATURE_ORDER

        # General models
        general = _try_load_bundle(model_root / "general")

        # Vehicle-specific models
        vehicles: dict[str, StateModelBundle] = {}
        for candidate in model_root.iterdir():
            if candidate.is_dir() and candidate.name not in {"general", "score_distributions"}:
                bundle = _try_load_bundle(candidate)
                if bundle:
                    vehicles[candidate.name] = bundle

        n_states = len(general.available_states) if general else 0
        n_vehicles = len(vehicles)
        logger.info(
            "[MODEL_LOADER] Loaded: general=%s (%d states), vehicles=%d, kmeans=%s",
            general is not None, n_states, n_vehicles, kmeans is not None,
        )
        return RuntimeModelStore(kmeans, state_scaler, state_mapping, state_feats, general, vehicles)

    except Exception as exc:
        logger.error("[MODEL_LOADER] Model loading failed: %s", exc, exc_info=True)
        return RuntimeModelStore(None, None, {}, [], None, {})


def compute_model_features(state: "CanIdState", timestamp: float, payload: tuple[int, ...], can_id_entropy: float = 0.0) -> dict[str, float]:  # type: ignore[name-defined]
    """
    Build a training-compatible feature vector from the runtime CanIdState deques.

    All clip+log transforms match core/feature_engineering.py build_features() exactly,
    so the vector lands in the same space as what the IsolationForest was trained on.
    """
    intervals = list(state.intervals) if state.intervals else []
    byte_diffs_list = list(state.byte_diffs) if state.byte_diffs else []

    n_int = len(intervals)
    n_bd = len(byte_diffs_list)

    # ── Timing features ────────────────────────────────────────────────────────
    dt = intervals[-1] if n_int > 0 else 0.0
    mean_dt = float(np.mean(intervals)) if n_int > 0 else 0.0
    std_dt = float(np.std(intervals)) if n_int > 0 else 0.0
    var_dt = float(np.var(intervals)) if n_int > 0 else 0.0
    msg_freq = 1.0 / (mean_dt + 1e-3)

    # burstiness = std / mean (coefficient of variation of timing)
    burstiness_raw = std_dt / (mean_dt + 1e-6)

    # inter_arrival_cv: same formula, using rolling window
    inter_arrival_cv_raw = std_dt / (mean_dt + 1e-6)

    # msg_rate: frames per second since first observed
    state.frame_count += 1
    if state.first_seen_ts is None:
        state.first_seen_ts = timestamp
    elapsed = max(timestamp - state.first_seen_ts, 1e-6)
    msg_rate_raw = state.frame_count / elapsed

    # ── Byte / payload features ────────────────────────────────────────────────
    bd = byte_diffs_list[-1] if n_bd > 0 else 0.0
    mean_bd = float(np.mean(byte_diffs_list)) if n_bd > 0 else 0.0
    std_bd = float(np.std(byte_diffs_list)) if n_bd > 0 else 0.0
    max_bd = float(np.max(byte_diffs_list)) if n_bd > 0 else 0.0

    # changed_bytes_count: compare current payload to previous payload
    prev = state.last_payload
    if prev is not None and len(prev) == len(payload):
        changed_bytes = float(sum(1 for a, b in zip(prev, payload) if a != b))
    else:
        changed_bytes = 0.0

    # payload_entropy: Shannon entropy of the 8 frame bytes (base-2)
    if payload:
        counts = np.bincount(np.array(payload, dtype=np.uint8), minlength=256).astype(np.float64)
        probs = counts[counts > 0] / max(len(payload), 1)
        payload_ent_raw = float(-np.sum(probs * np.log2(probs + 1e-12)))
    else:
        payload_ent_raw = 0.0

    # ── Apply clip + log1p (matching feature_engineering.py pipeline) ──────────
    def _cl(val: float, lo: float, hi: float) -> float:
        return float(np.log1p(np.clip(val, lo, hi)))

    return {
        "time_diff":             _cl(dt,                   0.0, 0.05),
        "rolling_std_time_diff": _cl(std_dt,               0.0, 0.05),
        "rolling_mean_byte_diff":_cl(mean_bd,              0.0, 50.0),
        "rolling_byte_diff_std": _cl(std_bd,               0.0, 50.0),
        "rolling_max_byte_diff": _cl(max_bd,               0.0, 50.0),
        "msg_frequency":         _cl(msg_freq,             0.0, 100.0),
        "byte_diff":             _cl(bd,                   0.0, 50.0),
        "changed_bytes_count":   float(np.clip(changed_bytes, 0.0, 8.0)),
        "msg_rate":              _cl(msg_rate_raw,         0.0, 5000.0),
        "rolling_var_time_diff": _cl(var_dt,               0.0, 0.1),
        "burstiness":            _cl(burstiness_raw,       0.0, 100.0),
        "can_id_entropy":        _cl(can_id_entropy,       0.0, 20.0),
        "payload_entropy":       _cl(payload_ent_raw,      0.0, 8.0),
        "inter_arrival_cv":      _cl(inter_arrival_cv_raw, 0.0, 50.0),
    }
