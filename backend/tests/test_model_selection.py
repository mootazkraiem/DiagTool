"""Vehicle / AI model selection: the listing the UI offers and the scoring it drives.

Expected sets are read independently from the model directories on disk, so the
tests check the loader's listing against the files rather than against itself.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import pytest

from backend.ml.runtime.model_loader import list_available_models
from backend.ml.runtime.realtime_engine import CanFrame, RealtimeEngine
from backend.ml.runtime.runtime_config import VALIDATION_CONFIG
from backend.ml.runtime.vehicle_scoring import score_frames

REPO = Path(__file__).resolve().parents[2]
MODELS = REPO / "assets" / "models"
REPLAY = REPO / "assets" / "Validation" / "validation_fuzzy_replay.csv"


def _dirs_with_model_files() -> list[str]:
    return sorted(
        d.name for d in MODELS.iterdir()
        if d.is_dir() and d.name not in {"general", "score_distributions"} and any(d.glob("model_*.joblib"))
    )


def _replay_frames(n: int) -> pd.DataFrame:
    rows = []
    with REPLAY.open() as fh:
        for line in fh:
            parts = line.strip().split(",")
            if len(parts) < 2:
                continue
            payload = [int(b, 16) for b in parts[2:10]] + [0] * (8 - len(parts[2:10]))
            rows.append({"timestamp": float(parts[0]), "can_id": int(parts[1], 16),
                         **{f"b{i}": payload[i] for i in range(8)}})
            if len(rows) >= n:
                break
    return pd.DataFrame(rows)


def test_general_model_is_listed_first() -> None:
    assert list_available_models()[0]["id"] == "general"


def test_every_vehicle_bundle_on_disk_is_listed() -> None:
    listed = [m["id"] for m in list_available_models()[1:]]
    assert listed == _dirs_with_model_files()
    assert len(listed) >= 14


def test_threshold_only_directories_are_not_offered() -> None:
    ids = {m["id"] for m in list_available_models()}
    # These folders hold thresholds but no trained model files.
    assert "byd_atto_3" not in ids
    assert "ford_mustang_mach-e" not in ids


def test_every_listed_state_has_its_model_and_scaler() -> None:
    for model in list_available_models():
        for state in model["states"]:
            assert (MODELS / model["id"] / f"model_{state}.joblib").exists()
            assert (MODELS / model["id"] / f"scaler_{state}.joblib").exists()


def test_score_frames_keeps_rows_and_produces_the_pipeline_columns() -> None:
    frames = _replay_frames(600)
    scored = score_frames(frames, "nissan_leaf_2019")
    assert len(scored) == len(frames)
    assert list(scored["timestamp"]) == list(frames["timestamp"])
    assert set(scored["anomaly"].unique()) <= {-1, 1}
    assert scored["anomaly_score"].between(0.0, 1.0).all()
    assert {"cluster", "vehicle_state"} <= set(scored.columns)


def test_batch_scoring_equals_per_frame_scoring() -> None:
    """The batch path must return exactly what the per-sample path returns."""
    from backend.ml.runtime.model_loader import compute_model_features, load_models

    store = load_models()
    engine = RealtimeEngine(VALIDATION_CONFIG, vehicle_id="nissan_leaf_2019", score_ml=False)
    frames = _replay_frames(400)

    vectors = []
    for row in frames.itertuples(index=False):
        payload = tuple(int(getattr(row, f"b{i}")) for i in range(8))
        out = engine.process_frame(CanFrame(timestamp=row.timestamp, can_id=row.can_id, payload=payload))
        vectors.append(compute_model_features(engine.state.get(row.can_id), row.timestamp, payload,
                                              float(out.get("can_id_entropy", 0.0))))

    states = store.classify_states(vectors)
    assert states == [store.classify_state(v) for v in vectors]

    batched = store.score_many(states, vectors, vehicle="nissan_leaf_2019")
    one_by_one = [store.score(s, v, vehicle="nissan_leaf_2019") for s, v in zip(states, vectors)]
    assert batched == pytest.approx(one_by_one, abs=1e-9)


def test_selected_model_changes_the_ml_scores() -> None:
    """The same frames scored with GENERAL and with a vehicle model must differ in the ML layer."""
    frames = _replay_frames(1500)

    def ml_scores(model_id: str) -> list[float]:
        engine = RealtimeEngine(VALIDATION_CONFIG, vehicle_id=model_id)
        out = []
        for row in frames.itertuples(index=False):
            payload = tuple(int(getattr(row, f"b{i}")) for i in range(8))
            out.append(float(engine.process_frame(CanFrame(timestamp=row.timestamp, can_id=row.can_id, payload=payload))["ml_norm"]))
        return out

    general = ml_scores("general")
    vehicle = ml_scores("nissan_leaf_2019")
    differing = sum(1 for a, b in zip(general, vehicle) if abs(a - b) > 1e-9)
    assert differing > 0, "vehicle model produced identical ML scores to the general model"


def test_models_report_their_training_date():
    """LAST TRAINING in Settings: the date the state models were written."""
    import re
    models = {m["id"]: m for m in list_available_models()}
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", models["general"]["trained_at"])
    assert all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", m["trained_at"]) for m in models.values())
