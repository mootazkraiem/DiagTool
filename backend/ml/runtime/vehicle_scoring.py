"""
vehicle_scoring.py
──────────────────
Score a batch of parsed CAN frames with a selected trained model.

Used by the offline ``/analyze`` endpoint when the user picks a vehicle-specific
model. It adds no detection rule of its own:

* frames run through the same ``RealtimeEngine`` the replay runner and the
  offline session analyzer use, so the per-CAN-ID feature state is built exactly
  as it is at runtime;
* the features are then classified and scored by the selected bundle through
  ``RuntimeModelStore`` - the same models, thresholds and normalization, called
  in batch rather than once per frame (per-frame IsolationForest calls cost
  ~79 ms each, which turns a whole-file analysis into minutes);
* a frame is anomalous when the model's own normalized score reaches 0.5, which
  is that model's trained threshold. This mirrors the general path, where the
  verdict is the general IsolationForest's own ``predict``.

The result carries the three columns the rest of ``/analyze`` reads from the
general engine's ``predict`` - ``anomaly`` (-1 anomalous / 1 normal),
``anomaly_score`` and ``cluster`` - so the context builder, post-ML pipeline,
explanations, de-duplication and incident grouping run unchanged.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backend.ml.runtime.model_loader import compute_model_features
from backend.ml.runtime.realtime_engine import CanFrame, RealtimeEngine
from backend.ml.runtime.runtime_config import VALIDATION_CONFIG, RuntimeConfig

_BYTE_COLS = [f"b{i}" for i in range(8)]

#: A model's trained threshold sits at 0.5 once normalized (see StateModelBundle.score).
MODEL_THRESHOLD = 0.5


def score_frames(frames: pd.DataFrame, model_id: str, cfg: RuntimeConfig = VALIDATION_CONFIG) -> pd.DataFrame:
    """Return a copy of ``frames`` scored by ``model_id``, rows kept in order.

    ``cluster`` numbers the vehicle states the model's state classifier assigned
    (sorted by name); ``vehicle_state`` keeps the state names themselves.
    """
    engine = RealtimeEngine(cfg, vehicle_id=model_id, score_ml=False)

    timestamps = frames["timestamp"].to_numpy(dtype=float)
    can_ids = frames["can_id"].to_numpy(dtype=np.int64)
    payload_cols = [c for c in _BYTE_COLS if c in frames.columns]
    payloads = (frames[payload_cols].fillna(0).astype(int).to_numpy()
                if payload_cols else np.zeros((len(frames), 0), dtype=int))

    feature_vecs: list[dict[str, float]] = []
    for ts, can_id, raw in zip(timestamps, can_ids, payloads):
        payload = (tuple(int(b) for b in raw) + (0,) * 8)[:8]
        out = engine.process_frame(CanFrame(timestamp=float(ts), can_id=int(can_id), payload=payload))
        state = engine.state.get(int(can_id))
        feature_vecs.append(
            compute_model_features(state, float(ts), payload, float(out.get("can_id_entropy", 0.0)))
        )

    states = engine.models.classify_states(feature_vecs)
    scores = engine.models.score_many(states, feature_vecs, vehicle=model_id)
    score_arr = np.asarray([0.0 if s is None else float(s) for s in scores], dtype=float)

    result = frames.copy()
    result["anomaly_score"] = score_arr
    result["anomaly"] = np.where(score_arr >= MODEL_THRESHOLD, -1, 1)
    state_index = {name: i for i, name in enumerate(sorted(set(states)))}
    result["cluster"] = [state_index[s] for s in states]
    result["vehicle_state"] = states
    return result
