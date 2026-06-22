from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass


@dataclass
class CanIdState:
    last_timestamp: float | None = None
    last_payload: tuple[int, ...] | None = None
    intervals: deque[float] | None = None
    entropy_like: deque[float] | None = None
    hamming: deque[float] | None = None
    scores: deque[float] | None = None
    transitions: deque[tuple[tuple[int, ...], tuple[int, ...]]] | None = None
    # Extended state for model-feature computation
    byte_diffs: deque[float] | None = None   # raw byte-level L1 differences per frame
    frame_count: int = 0                      # total frames seen for this CAN-ID
    first_seen_ts: float | None = None        # timestamp of first frame (for msg_rate)
    # ML stride cache — avoids sklearn inference on every frame
    ml_frame_count: int = 0
    last_ml_norm: float = 0.0
    last_vehicle_state: str = "unknown"


# CAN 2.0B has at most 2048 standard IDs. Capping at 500 active entries is
# generous for any legitimate vehicle bus; beyond this we're being fuzz-attacked.
_MAX_CAN_IDS = 500


class StateManager:
    def __init__(self, interval_window: int, payload_window: int, score_window: int, transition_window: int) -> None:
        self.interval_window = interval_window
        self.payload_window = payload_window
        self.score_window = score_window
        self.transition_window = transition_window
        self._store: OrderedDict[int, CanIdState] = OrderedDict()

    def get(self, can_id: int) -> CanIdState:
        if can_id not in self._store:
            if len(self._store) >= _MAX_CAN_IDS:
                self._store.popitem(last=False)  # evict least-recently-used entry
            self._store[can_id] = CanIdState(
                intervals=deque(maxlen=self.interval_window),
                entropy_like=deque(maxlen=self.payload_window),
                hamming=deque(maxlen=self.payload_window),
                scores=deque(maxlen=self.score_window),
                transitions=deque(maxlen=self.transition_window),
                byte_diffs=deque(maxlen=self.payload_window),
            )
        else:
            self._store.move_to_end(can_id)  # mark as recently used
        return self._store[can_id]

    def active_can_ids(self) -> int:
        return len(self._store)

    def reset(self) -> None:
        self._store.clear()
