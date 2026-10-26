"""
dataset_facts.py
────────────────
Plain facts about a loaded capture, for the Dashboard's dataset card.

Everything returned is measured from the file itself or read from the selected
model's corpus.json (which recordings trained the model and which were held
back for testing). Nothing is estimated or typed in by hand: when a fact is not
known (no model, no corpus) the field is empty and the card says so.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable

#: Display names for model ids whose id does not read well on its own.
VEHICLE_NAMES = {
    "jaguar_ipace": "Jaguar I-PACE",
    "kia_ev6": "Kia EV6",
    "nissan_leaf_2019": "Nissan Leaf (2019)",
    "road_ambient": "ROAD dataset (ambient traffic)",
    "general": "General model (no specific vehicle)",
}


def vehicle_name(model_id: str) -> str:
    mid = (model_id or "").strip()
    if not mid:
        return ""
    return VEHICLE_NAMES.get(mid, mid.replace("_", " ").title())


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def corpus_role(path: Path, model_id: str, model_root: Path) -> dict:
    """Whether the file trained the selected model, was held back to test it, or neither."""
    out = {"role": "", "model_version": "", "training_recordings": 0, "training_frames": 0,
           "holdout_recordings": 0}
    mid = (model_id or "").strip()
    corpus_path = model_root / mid / "corpus.json" if mid else None
    if corpus_path is None or not corpus_path.is_file():
        return out
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    manifest_path = model_root / mid / "manifest.json"
    if manifest_path.is_file():
        out["model_version"] = json.loads(manifest_path.read_text(encoding="utf-8")).get("model_version", "")

    training = corpus.get("training", {}).get("recordings", [])
    holdout = corpus.get("holdout", {}).get("recordings", [])
    out["training_recordings"] = len(training)
    out["training_frames"] = sum(int(r.get("frames") or 0) for r in training)
    out["holdout_recordings"] = len(holdout)

    digest = _sha256(path)
    name = path.name.lower()

    def matches(rec: dict) -> bool:
        if rec.get("sha256") == digest:
            return True
        return not rec.get("sha256") and Path(rec.get("path", "")).name.lower() == name

    if any(matches(r) for r in holdout):
        out["role"] = "holdout"
    elif any(matches(r) for r in training):
        out["role"] = "training"
    else:
        out["role"] = "outside"
    return out


def describe(path: Path, frames: Iterable[tuple[float, int, tuple]], model_id: str,
             model_root: Path) -> dict:
    frames = list(frames)
    times = [f[0] for f in frames]
    duration = (max(times) - min(times)) if len(times) > 1 else 0.0
    ids = {f[1] for f in frames}
    return {
        "file_name": path.name,
        "folder": path.parent.name,
        "model_id": model_id,
        "vehicle": vehicle_name(model_id),
        "frames": len(frames),
        "duration_s": round(duration, 3),
        "can_ids": len(ids),
        "rate_hz": round((len(frames) - 1) / duration, 1) if duration > 0 else 0.0,
        **corpus_role(path, model_id, model_root),
    }
