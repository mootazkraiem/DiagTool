from __future__ import annotations

import math
from collections import Counter
import numpy as np

# Pre-compute bit counts for faster hamming distance
_BIT_COUNTS = np.zeros(256, dtype=np.uint8)
for i in range(256):
    _BIT_COUNTS[i] = bin(i).count('1')

from backend.ml.runtime.state_manager import CanIdState


def _hamming_bits(a: tuple[int, ...], b: tuple[int, ...]) -> int:
    """Fast hamming distance calculation using lookup table."""
    # Use lookup table for bit counting - much faster than numpy bit_count
    total = 0
    for x, y in zip(a, b):
        total += _BIT_COUNTS[x ^ y]
    return int(total)


def update_timing(state: CanIdState, timestamp: float) -> dict[str, float]:
    dt = 0.0
    if state.last_timestamp is not None:
        dt = max(0.0, timestamp - state.last_timestamp)
        state.intervals.append(dt)
    state.last_timestamp = timestamp

    # Use numpy for fast mean/std calculation
    if state.intervals:
        vals = np.array(state.intervals)
        mean_dt = np.mean(vals)
        std_dt = np.std(vals)
    else:
        mean_dt = 0.0
        std_dt = 0.0

    return {"dt": dt, "timing_mean": mean_dt, "timing_std": std_dt}


def update_payload(state: CanIdState, payload: tuple[int, ...]) -> dict[str, float]:
    if state.last_payload is None:
        state.last_payload = payload
        return {"hamming": 0.0, "payload_delta": 0.0, "entropy_like": 0.0, "continuity": 0.0}

    prev = state.last_payload
    hd = float(_hamming_bits(prev, payload))

    # Fast delta calculation using numpy
    prev_arr = np.array(prev, dtype=np.uint8)
    curr_arr = np.array(payload, dtype=np.uint8)
    delta = np.mean(np.abs(prev_arr - curr_arr))

    state.hamming.append(hd)
    state.transitions.append((prev, payload))
    state.last_payload = payload

    # Optimized entropy calculation - only update every N frames for performance
    if len(state.transitions) % 100 == 0:  # Update entropy every 100 frames (was 50)
        # Convert deque to list for slicing
        recent_transitions = list(state.transitions)[-50:] if len(state.transitions) > 50 else list(state.transitions)
        counts = Counter(recent_transitions)
        top_ratio = max(counts.values()) / max(len(recent_transitions), 1)
        ent_like = 1.0 - top_ratio
        state.entropy_like.append(ent_like)
    else:
        # Use last calculated entropy
        ent_like = state.entropy_like[-1] if state.entropy_like else 0.0

    continuity = (hd / 64.0) + (delta / 255.0)
    return {
        "hamming": hd,
        "payload_delta": float(delta),
        "entropy_like": float(ent_like),
        "continuity": float(continuity),
    }


def update_ml_like(timing: dict[str, float], payload: dict[str, float]) -> float:
    # Keeps runtime inference lightweight while preserving frozen v1 design intent.
    raw = 0.5 * timing.get("timing_std", 0.0) + 0.5 * payload.get("continuity", 0.0)
    return float(1.0 / (1.0 + math.exp(-raw)))
