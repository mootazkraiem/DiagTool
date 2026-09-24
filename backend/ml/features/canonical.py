"""
canonical.py
────────────
The one feature definition for the per-vehicle anomaly models: training,
offline analysis and the live engine all call this module, so a feature means
the same thing everywhere.

It is written as a stream - one frame in, one feature vector out - because the
live engine can only ever see the past. Batch use (training, offline analysis)
is the same stream run over a whole recording, so batch and live agree by
construction rather than by two implementations kept in step.

Definitions (per CAN identifier, over that identifier's own frames):

    time_diff                 seconds since this identifier's previous frame
    rolling_mean_time_diff    mean of its last WINDOW time_diffs
    rolling_std_time_diff     population std of its last WINDOW time_diffs
    byte_diff                 mean |b_i - prev b_i| over the 8 payload bytes,
                              in integer arithmetic (no uint8 wraparound)
    rolling_mean_byte_diff    mean of its last WINDOW byte_diffs
    rolling_std_byte_diff     population std of its last WINDOW byte_diffs
    rolling_max_byte_diff     max of its last WINDOW byte_diffs
    changed_bytes_count       number of payload bytes that changed (0-8)
    payload_entropy           Shannon entropy (bits) of the 8 payload bytes

Transforms: time features are expressed in milliseconds and log1p'd; byte
features are log1p'd; the count and the entropy are used as they are. There is
no clipping and no normalisation against the capture being scored.

Warm-up: a frame yields features only once its identifier has WINDOW
time_diffs behind it (WINDOW + 1 frames). Earlier frames yield None - there is
no value for them, and none is invented.

Payloads shorter than 8 bytes are right-padded with zeros, longer ones cut to 8.
A timestamp earlier than the identifier's previous one gives time_diff 0.
"""

from __future__ import annotations

import math
from collections import deque
from typing import Iterable, Sequence

import numpy as np

FEATURE_VERSION = "canonical-1"
WINDOW = 10
N_BYTES = 8

FEATURES: tuple[str, ...] = (
    "time_diff",
    "rolling_mean_time_diff",
    "rolling_std_time_diff",
    "byte_diff",
    "rolling_mean_byte_diff",
    "rolling_std_byte_diff",
    "rolling_max_byte_diff",
    "changed_bytes_count",
    "payload_entropy",
)


def _payload8(payload: Iterable[int]) -> tuple[int, ...]:
    p = tuple(int(b) for b in payload)[:N_BYTES]
    return p + (0,) * (N_BYTES - len(p))


def _mean_std(values: Sequence[float]) -> tuple[float, float]:
    n = len(values)
    m = sum(values) / n
    return m, math.sqrt(sum((v - m) * (v - m) for v in values) / n)


def _entropy(p: tuple[int, ...]) -> float:
    counts: dict[int, int] = {}
    for b in p:
        counts[b] = counts.get(b, 0) + 1
    h = 0.0
    for c in counts.values():
        q = c / N_BYTES
        h -= q * math.log2(q)
    return h


class _IdState:
    __slots__ = ("last_ts", "last_payload", "intervals", "diffs")

    def __init__(self, ts: float, payload: tuple[int, ...]) -> None:
        self.last_ts = ts
        self.last_payload = payload
        self.intervals: deque[float] = deque(maxlen=WINDOW)
        self.diffs: deque[float] = deque(maxlen=WINDOW)


class CanonicalFeatureStream:
    """Per-identifier history; ``update`` returns the frame's features or None."""

    def __init__(self) -> None:
        self._ids: dict[int, _IdState] = {}

    def reset(self) -> None:
        self._ids.clear()

    def update(self, timestamp: float, can_id: int, payload: Iterable[int]) -> list[float] | None:
        ts = float(timestamp)
        p = _payload8(payload)
        st = self._ids.get(can_id)
        if st is None:
            self._ids[can_id] = _IdState(ts, p)
            return None

        dt = ts - st.last_ts
        if dt < 0.0:
            dt = 0.0
        prev = st.last_payload
        diffs = [abs(a - b) for a, b in zip(p, prev)]
        byte_diff = sum(diffs) / N_BYTES
        changed = sum(1 for d in diffs if d)

        st.intervals.append(dt)
        st.diffs.append(byte_diff)
        st.last_ts = ts
        st.last_payload = p

        if len(st.intervals) < WINDOW:
            return None

        mean_dt, std_dt = _mean_std(st.intervals)
        mean_bd, std_bd = _mean_std(st.diffs)
        return [
            math.log1p(dt * 1000.0),
            math.log1p(mean_dt * 1000.0),
            math.log1p(std_dt * 1000.0),
            math.log1p(byte_diff),
            math.log1p(mean_bd),
            math.log1p(std_bd),
            math.log1p(max(st.diffs)),
            float(changed),
            _entropy(p),
        ]


def compute_features(
    timestamps: Sequence[float],
    can_ids: Sequence[int],
    payloads: Sequence[Sequence[int]],
) -> tuple[np.ndarray, np.ndarray]:
    """Features for frames in the order given.

    Returns ``(X, ready)``: X is (n, len(FEATURES)) float64 with NaN rows where
    ``ready`` is False (warm-up). The caller is responsible for passing frames
    in chronological order; this function does not reorder anything.
    """
    n = len(timestamps)
    x = np.full((n, len(FEATURES)), np.nan, dtype=np.float64)
    ready = np.zeros(n, dtype=bool)
    stream = CanonicalFeatureStream()
    for i, (ts, cid, pl) in enumerate(zip(timestamps, can_ids, payloads)):
        vec = stream.update(ts, int(cid), pl)
        if vec is not None:
            x[i] = vec
            ready[i] = True
    return x, ready


def compute_features_frame(frames) -> tuple[np.ndarray, np.ndarray]:
    """``compute_features`` over a DataFrame with timestamp, can_id, b0..b7."""
    cols = [f"b{i}" for i in range(N_BYTES)]
    missing = [c for c in ("timestamp", "can_id", *cols) if c not in frames.columns]
    if missing:
        raise ValueError(f"cannot build canonical features without columns {missing}")
    payloads = frames[cols].to_numpy(dtype=np.int64).tolist()
    return compute_features(
        frames["timestamp"].to_numpy(dtype=np.float64).tolist(),
        frames["can_id"].to_numpy(dtype=np.int64).tolist(),
        payloads,
    )
