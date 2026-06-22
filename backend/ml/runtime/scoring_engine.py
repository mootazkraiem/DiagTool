from __future__ import annotations

from collections import deque
import numpy as np


class ScoringEngine:
    def __init__(
        self,
        short_w: int,
        med_w: int,
        long_w: int,
        w_t: float,
        w_p: float,
        w_m: float,
        w_tmp: float,
        low_threshold: float = 0.30,
        medium_threshold: float = 0.55,
        high_threshold: float = 0.80,
        critical_threshold: float = 1.00,
    ) -> None:
        self.short = deque(maxlen=short_w)
        self.medium = deque(maxlen=med_w)
        self.long = deque(maxlen=long_w)
        s = w_t + w_p + w_m + w_tmp
        self.w_t, self.w_p, self.w_m, self.w_tmp = w_t / s, w_p / s, w_m / s, w_tmp / s
        self.low_threshold = float(low_threshold)
        self.medium_threshold = float(medium_threshold)
        self.high_threshold = float(high_threshold)
        self.critical_threshold = float(critical_threshold)

    def _risk_level(self, score: float) -> str:
        if score >= self.critical_threshold:
            return "CRITICAL"
        if score >= self.high_threshold:
            return "HIGH"
        if score >= self.medium_threshold:
            return "MEDIUM"
        if score >= self.low_threshold:
            return "LOW"
        return "LOW"

    def score(self, timing_norm: float, payload_norm: float, ml_norm: float) -> dict[str, float | str]:
        base = self.w_t * timing_norm + self.w_p * payload_norm + self.w_m * ml_norm
        self.short.append(base)
        self.medium.append(base)
        self.long.append(base)

        # Fast persistence calculation using numpy
        if len(self.long) > 0:
            long_arr = np.array(list(self.long))
            persistence = np.mean(long_arr > self.high_threshold)
        else:
            persistence = 0.0

        fused = base + self.w_tmp * persistence
        return {
            "timing_norm": timing_norm,
            "payload_norm": payload_norm,
            "ml_norm": ml_norm,
            "persistence_score": persistence,
            "fusion_score": fused,
            "risk_level": self._risk_level(fused),
        }
