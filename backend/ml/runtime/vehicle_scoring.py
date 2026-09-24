"""
vehicle_scoring.py
──────────────────
Score a batch of parsed CAN frames with a selected trained model.

Used by the offline ``/analyze`` endpoint when the user picks a vehicle-specific
model. It adds no detection rule of its own:

* the model family is loaded through its manifest, which verifies that the
  state classifier and the anomaly models were produced together; a family
  without a valid manifest is refused (``ManifestError``), never scored;
* the vehicle-state classifier is fed the feature space its manifest names -
  the live engine's runtime vector, or the training-parity features - and a
  frame it cannot route to a trained model is marked unresolved;
* the anomaly score comes from the features the bundle was trained on, built by
  the training feature pipeline itself and normalised per CAN ID over the whole
  capture, as training normalised each source (``training_parity_features``),
  then scored by the selected bundle's saved scaler, forest and threshold in
  batch (per-frame IsolationForest calls cost ~79 ms each, which turns a
  whole-file analysis into minutes);
* a frame is anomalous when the model's own normalized score reaches 0.5, which
  is that model's trained threshold. This mirrors the general path, where the
  verdict is the general IsolationForest's own ``predict``.

The result carries the three columns the rest of ``/analyze`` reads from the
general engine's ``predict`` - ``anomaly`` (-1 anomalous / 1 normal, and 0 for
an unresolved frame, which is neither), ``anomaly_score`` and ``cluster`` - so
the context builder, post-ML pipeline, explanations, de-duplication and
incident grouping run unchanged.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from backend.ml.runtime.model_loader import RUNTIME_FEATURE_ORDER, _default_assets_root, compute_model_features
from backend.ml.features import canonical
from backend.ml.runtime.model_manifest import (
    FAMILY_SCHEMA_VERSION,
    ID_SCHEMA_VERSION,
    SCORED,
    UNRESOLVED,
    FamilyModel,
    IdModelFamily,
    load_family_model,
    load_id_family,
    load_validated_bundle,
    manifest_schema,
)
from backend.ml.runtime.realtime_engine import CanFrame, RealtimeEngine
from backend.ml.runtime.runtime_config import VALIDATION_CONFIG, RuntimeConfig

_BYTE_COLS = [f"b{i}" for i in range(8)]

#: A model's trained threshold sits at 0.5 once normalized (see StateModelBundle.score).
MODEL_THRESHOLD = 0.5


def training_parity_features(frames: pd.DataFrame) -> pd.DataFrame:
    """Anomaly-model features for a whole capture, built the way training built them.

    The vehicle bundles were fitted by backend.ml.state_based_pipeline.train(),
    which prepares every source through backend.ml.feature_engineering:

        build_features         rolling per-CAN-ID features, clip, log1p
        normalize_per_can_id   (x - mu) / (sd + 1e-6), mu and population sd
                               of each feature over that identifier's rows in
                               that source
        RobustScaler, IsolationForest

    Both functions are called here unchanged, rather than re-implemented, so the
    feature definitions and window semantics are training's own - including
    rolling_min_byte_diff and rolling_range_byte_diff, which the runtime feature
    vector has never contained.

    The normalisation statistics are the capture's own, deliberately. Training
    did not persist mu and sd: it computed them over each source it was fitting
    and discarded them, so every identifier was measured against its own
    behaviour in the same recording. Applying some other recording's statistics
    would be a different transform. Computing them over the complete capture
    under analysis is the same one - which is why this is offline only: a live
    stream has no complete capture to compute them over.

    build_features works in (can_id, timestamp) order, which its rolling windows
    need. The frames are handed over already in that order (a stable sort), the
    result is checked row for row against it, and the output is put back in the
    caller's order, which for scoring is chronological.

    Returns one row per input frame, in input order.
    """
    from backend.ml import feature_engineering as training_fe

    missing = [c for c in ("timestamp", "can_id", *_BYTE_COLS) if c not in frames.columns]
    if missing:
        raise ValueError(f"cannot build training features without columns {missing}")

    timestamps = frames["timestamp"].to_numpy(dtype=float)
    can_ids = frames["can_id"].to_numpy(dtype=np.int64)
    order = np.lexsort((timestamps, can_ids))          # stable: can_id, then timestamp

    grouped = frames.iloc[order][["timestamp", "can_id", *_BYTE_COLS]].reset_index(drop=True)
    features = training_fe.build_features(grouped)

    # build_features sorts again and drops incomplete rows. Pairing its rows
    # with the input by position is only valid if it kept every row in the
    # order it was given; otherwise stop rather than hand a frame another
    # frame's features.
    if (len(features) != len(grouped)
            or not np.array_equal(features["can_id"].to_numpy(dtype=np.int64), grouped["can_id"].to_numpy(dtype=np.int64))
            or not np.allclose(features["timestamp"].to_numpy(dtype=float), grouped["timestamp"].to_numpy(dtype=float))):
        raise ValueError(
            "training feature pipeline did not return one row per frame in (can_id, timestamp) "
            f"order ({len(features)} rows for {len(grouped)} frames)"
        )

    normalized = training_fe.normalize_per_can_id(features)

    inverse = np.empty_like(order)
    inverse[order] = np.arange(len(order))
    return normalized.iloc[inverse].reset_index(drop=True)


def global_can_id_entropy(can_ids: pd.Series) -> float:
    """Shannon entropy of the identifier distribution over a whole capture.

    This is the definition the models were fitted to: training computes one
    value per dataset (backend.ml.core.feature_engineering.build_features), so
    every training row carried the same number.

    The live engine cannot use it - a stream has no "whole capture" - and
    estimates it instead from a rolling window of the last 200 identifiers.
    That estimator agrees closely once it is warm (2.0722 against a training
    value of 2.0768 on the reference recording) but reports 0.0 until it has
    seen ten identifiers, which is a value no driving capture produces. The
    state classifier, which does consume this feature, then reads those opening
    frames as "parking", and a vehicle with no parking model leaves them
    unscored.

    Batch scoring has the whole file in hand before it starts, so it uses the
    training definition directly and has no warm-up at all.
    """
    if can_ids.empty:
        return 0.0
    freq = can_ids.value_counts(normalize=True)
    return float(-(freq * np.log(freq + 1e-12)).sum())


def score_frames(
    frames: pd.DataFrame,
    model_id: str,
    cfg: RuntimeConfig = VALIDATION_CONFIG,
    model_root: Path | None = None,
) -> pd.DataFrame:
    """Return a copy of ``frames`` scored by ``model_id``, rows kept in order.

    The model family is loaded through its manifest (model_manifest.py), which
    proves the state classifier, feature lists, scalers, models and thresholds
    belong to one trained version. If they do not, ``ManifestError`` is raised
    and nothing is scored: an unverifiable combination produces no numbers at
    all rather than plausible-looking wrong ones.

    A frame whose state cannot be resolved to a trained model - the classifier
    failed, returned a cluster its mapping does not name, or chose a state the
    family has no model for - is reported as unresolved, not assigned a default
    state or a zero score:

        anomaly           -1 anomalous, 1 normal, 0 unresolved
        anomaly_score     0-1, NaN when unresolved
        vehicle_state     the routed state, or "unresolved"
        state_resolution  "" when resolved, otherwise the reason
        cluster           index of the state (sorted by name), -1 when unresolved
    """
    root = model_root if model_root is not None else _default_assets_root() / "models"
    schema = manifest_schema(root, model_id)
    if schema == ID_SCHEMA_VERSION:
        return _score_id_models(frames, load_id_family(root, model_id))
    if schema == FAMILY_SCHEMA_VERSION:
        return _score_single_model(frames, load_family_model(root, model_id))
    bundle = load_validated_bundle(root, model_id, runtime_feature_order=RUNTIME_FEATURE_ORDER)
    clf = bundle.classifier

    # Anomaly-model features, built and normalised the way training built them.
    parity = training_parity_features(frames)

    if clf.input_space == "runtime":
        vectors = _runtime_feature_vectors(frames, model_id, cfg)
        absent = sorted({f for v in vectors for f in clf.features if f not in v})
        if absent:
            raise ValueError(f"state classifier requires features the runtime did not produce: {absent}")
        x_state = np.array([[v[f] for f in clf.features] for v in vectors], dtype=np.float64)
    else:
        absent = [f for f in clf.features if f not in parity.columns]
        if absent:
            raise ValueError(f"state classifier requires features that were not produced: {absent}")
        x_state = parity[clf.features].to_numpy(dtype=np.float64)

    states, reasons = bundle.resolve_states(x_state.reshape(len(frames), len(clf.features)))
    scores = bundle.score(states, parity)
    score_arr = np.asarray([np.nan if s is None else float(s) for s in scores], dtype=float)

    result = frames.copy()
    result["anomaly_score"] = score_arr
    result["anomaly"] = np.where(np.isnan(score_arr), 0, np.where(score_arr >= MODEL_THRESHOLD, -1, 1))
    state_index = {name: i for i, name in enumerate(sorted(set(states) - {UNRESOLVED}))}
    result["cluster"] = [state_index.get(s, -1) for s in states]
    result["vehicle_state"] = states
    result["state_resolution"] = reasons
    return result


def _score_id_models(frames: pd.DataFrame, family: IdModelFamily) -> pd.DataFrame:
    """Score with a per-CAN-ID family (schema 3) over canonical features.

    Each frame is scored only by its own identifier's model. A frame is
    unresolved - anomaly 0, no score, the reason in ``state_resolution`` - when
    its identifier has not filled its window yet ("warmup"), was too rare in
    training ("sparse_id"), never varied ("unmodelled_id") or never occurred
    in training at all ("unseen_id").
    """
    ts = frames["timestamp"].to_numpy(dtype=float)
    if len(ts) > 1 and (np.diff(ts) < 0).any():
        raise ValueError("frames must be in chronological order for canonical features")
    x, ready = canonical.compute_features_frame(frames)
    ids = frames["can_id"].to_numpy(dtype=np.int64)

    norm = np.full(len(frames), np.nan)
    flagged = np.zeros(len(frames), dtype=bool)
    reason = np.full(len(frames), f"warmup: fewer than {canonical.WINDOW + 1} frames of this identifier",
                     dtype=object)
    if ready.any():
        n_r, f_r, s_r = family.score_rows(x[ready], ids[ready])
        norm[ready], flagged[ready] = n_r, f_r
        reason[ready] = np.where(s_r == SCORED, "", s_r)
    scored = reason == ""

    result = frames.copy()
    result["anomaly_score"] = norm
    result["anomaly"] = np.where(~scored, 0, np.where(flagged, -1, 1))
    result["cluster"] = np.where(scored, 0, -1)
    result["vehicle_state"] = np.where(scored, "can_id_model", UNRESOLVED)
    result["state_resolution"] = reason
    return result


def _score_single_model(frames: pd.DataFrame, family: FamilyModel) -> pd.DataFrame:
    """Score with a one-model family over canonical features (schema 2).

    Features come from backend.ml.features.canonical - the definition the model
    was trained on and the live engine computes - over the frames in the order
    given, which must be chronological. No statistic is taken from the capture
    being scored. A frame whose identifier has not yet filled its window is
    unresolved ("warmup"), not scored.
    """
    ts = frames["timestamp"].to_numpy(dtype=float)
    if len(ts) > 1 and (np.diff(ts) < 0).any():
        raise ValueError("frames must be in chronological order for canonical features")
    x, ready = canonical.compute_features_frame(frames)
    score_arr = np.full(len(frames), np.nan)
    if ready.any():
        score_arr[ready] = family.score(x[ready])

    result = frames.copy()
    result["anomaly_score"] = score_arr
    result["anomaly"] = np.where(~ready, 0, np.where(score_arr >= MODEL_THRESHOLD, -1, 1))
    result["cluster"] = np.where(ready, 0, -1)
    result["vehicle_state"] = np.where(ready, "vehicle", UNRESOLVED)
    result["state_resolution"] = np.where(ready, "", f"warmup: fewer than {canonical.WINDOW + 1} frames of this identifier")
    return result


def _runtime_feature_vectors(frames: pd.DataFrame, model_id: str, cfg: RuntimeConfig) -> list[dict[str, float]]:
    """The live engine's per-frame feature vector, with whole-capture entropy."""
    engine = RealtimeEngine(cfg, vehicle_id=model_id, score_ml=False)

    timestamps = frames["timestamp"].to_numpy(dtype=float)
    can_ids = frames["can_id"].to_numpy(dtype=np.int64)
    payload_cols = [c for c in _BYTE_COLS if c in frames.columns]
    payloads = (frames[payload_cols].fillna(0).astype(int).to_numpy()
                if payload_cols else np.zeros((len(frames), 0), dtype=int))

    can_id_entropy = global_can_id_entropy(frames["can_id"])

    vectors: list[dict[str, float]] = []
    for ts, can_id, raw in zip(timestamps, can_ids, payloads):
        payload = (tuple(int(b) for b in raw) + (0,) * 8)[:8]
        # The engine still advances its per-identifier state here; only its
        # rolling entropy is set aside in favour of the whole-capture value.
        engine.process_frame(CanFrame(timestamp=float(ts), can_id=int(can_id), payload=payload))
        state = engine.state.get(int(can_id))
        vectors.append(compute_model_features(state, float(ts), payload, can_id_entropy))
    return vectors
