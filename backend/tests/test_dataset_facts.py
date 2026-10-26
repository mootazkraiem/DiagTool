"""Dataset card facts (backend/offline/dataset_facts.py): measured from the file,
role read from the model's corpus.json by content hash."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.offline import dataset_facts as df

FRAMES = [(0.0, 0x100, (0,) * 8), (0.5, 0x200, (1,) * 8), (1.0, 0x100, (2,) * 8), (2.0, 0x300, (3,) * 8)]


def _setup(tmp_path, role):
    log = tmp_path / "Some Car" / "drive.csv"
    log.parent.mkdir()
    log.write_text("payload", encoding="utf-8")
    digest = hashlib.sha256(log.read_bytes()).hexdigest()
    other = {"path": "x/other.csv", "sha256": "0" * 64, "frames": 900}
    mine = {"path": "x/drive.csv", "sha256": digest, "frames": 4}
    corpus = {"training": {"recordings": [other] + ([mine] if role == "training" else [])},
              "holdout": {"recordings": [mine] if role == "holdout" else []}}
    model = tmp_path / "models" / "some_car"
    model.mkdir(parents=True)
    (model / "corpus.json").write_text(json.dumps(corpus), encoding="utf-8")
    (model / "manifest.json").write_text(json.dumps({"model_version": "clean-2-002"}), encoding="utf-8")
    return log, tmp_path / "models"


def test_measured_facts(tmp_path):
    log, root = _setup(tmp_path, "holdout")
    out = df.describe(log, FRAMES, "some_car", root)
    assert (out["frames"], out["duration_s"], out["can_ids"], out["rate_hz"]) == (4, 2.0, 3, 1.5)
    assert out["folder"] == "Some Car" and out["vehicle"] == "Some Car"


def test_role_from_corpus_hash(tmp_path):
    for role in ("holdout", "training"):
        sub = tmp_path / role
        sub.mkdir()
        log, root = _setup(sub, role)
        out = df.describe(log, FRAMES, "some_car", root)
        assert out["role"] == role
        assert out["model_version"] == "clean-2-002"


def test_file_outside_corpus_and_training_totals(tmp_path):
    log, root = _setup(tmp_path, "none")
    out = df.describe(log, FRAMES, "some_car", root)
    assert out["role"] == "outside"
    assert (out["training_recordings"], out["training_frames"]) == (1, 900)


def test_no_model_means_unknown_role(tmp_path):
    log, root = _setup(tmp_path, "holdout")
    out = df.describe(log, FRAMES, "", root)
    assert out["role"] == "" and out["vehicle"] == ""


def test_vehicle_display_names():
    assert df.vehicle_name("jaguar_ipace") == "Jaguar I-PACE"
    assert df.vehicle_name("bmw_i3") == "Bmw I3"
