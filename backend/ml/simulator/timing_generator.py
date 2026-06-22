from __future__ import annotations

import random


PERIODS = [0.01, 0.02, 0.1, 0.5]


def next_timestamp(current: float, profile_idx: int) -> float:
    base = PERIODS[profile_idx % len(PERIODS)]
    jitter = random.uniform(-0.001, 0.001)
    burst = 0.0 if random.random() > 0.02 else random.uniform(-0.003, 0.003)
    return max(current + base + jitter + burst, current + 0.0001)
