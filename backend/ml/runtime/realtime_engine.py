from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
import sys
from pathlib import Path

import numpy as _np

try:
    from backend.ml.runtime.alert_system import AlertSystem
    from backend.ml.runtime.feature_updates import update_ml_like, update_payload, update_timing
    from backend.ml.runtime.model_loader import RuntimeModelStore, compute_model_features, load_models
    from backend.ml.runtime.runtime_config import DEFAULT_CONFIG, RuntimeConfig
    from backend.ml.runtime.scoring_engine import ScoringEngine
    from backend.ml.runtime.state_manager import StateManager
except ModuleNotFoundError:
    sys.path.append(str(Path(__file__).resolve().parents[3]))
    from backend.ml.runtime.alert_system import AlertSystem
    from backend.ml.runtime.feature_updates import update_ml_like, update_payload, update_timing
    from backend.ml.runtime.model_loader import RuntimeModelStore, compute_model_features, load_models
    from backend.ml.runtime.runtime_config import DEFAULT_CONFIG, RuntimeConfig
    from backend.ml.runtime.scoring_engine import ScoringEngine
    from backend.ml.runtime.state_manager import StateManager

# Thresholds for DoS frequency detection heuristic
_FREQ_ANOMALY_LOW_HZ = 500.0   # Hz — above baseline before flagging
_FREQ_ANOMALY_HIGH_HZ = 2000.0  # Hz — saturates at full anomaly score

# Run heavyweight ML inference every N frames per CAN-ID; reuse cached score in between.
# Entropy (global counter) recalculated every M global frames.
_ML_STRIDE = 5
_ENTROPY_STRIDE = 20


@dataclass
class CanFrame:
    timestamp: float
    can_id: int
    payload: tuple[int, ...]


class RealtimeEngine:
    def __init__(self, cfg: RuntimeConfig = DEFAULT_CONFIG, vehicle_id: str = "") -> None:
        self.cfg = cfg
        # Which per-vehicle model bundle to score against (see RuntimeModelStore.score).
        # Empty/unknown vehicle_id falls back to "general" — same as prior behavior.
        self.vehicle_id = vehicle_id or "general"
        self.state = StateManager(cfg.interval_window, cfg.payload_window, cfg.score_window, cfg.transition_window)
        self.scoring = ScoringEngine(
            cfg.temporal_short_window,
            cfg.temporal_medium_window,
            cfg.temporal_long_window,
            cfg.timing_weight,
            cfg.payload_weight,
            cfg.ml_weight,
            cfg.temporal_weight,
            cfg.low_threshold,
            cfg.medium_threshold,
            cfg.high_threshold,
            cfg.critical_threshold,
        )
        self.alerts = AlertSystem(cfg.alerts_path, cfg.alerts_csv_path, cooldown_seconds=cfg.cooldown_seconds)

        # Load trained IsolationForest models — safe no-op if models directory is absent
        self._models: RuntimeModelStore = load_models()
        print(f"[RUNTIME] Trained models loaded: {self._models.is_loaded}")

        # Global sliding window of recent CAN-IDs for cross-ID entropy (Fuzzy detection)
        self._recent_can_ids: deque[int] = deque(maxlen=200)
        self._global_frame_count: int = 0
        self._cached_entropy: float = 0.0

        print(f"[RUNTIME] Current alert threshold: {cfg.alert_threshold}")
        print(
            f"[RUNTIME] Severity thresholds: "
            f"LOW>={cfg.low_threshold}, MEDIUM>={cfg.medium_threshold}, "
            f"HIGH>={cfg.high_threshold}, CRITICAL>={cfg.critical_threshold}"
        )
        print(f"[RUNTIME] Current persistence threshold: {cfg.persistence_threshold}")
        print(f"[RUNTIME] Current temporal decay: {cfg.temporal_decay}")

    def process_frame(self, frame: CanFrame) -> dict[str, object]:
        st = self.state.get(frame.can_id)
        self._recent_can_ids.append(frame.can_id)

        timing = update_timing(st, frame.timestamp)
        payload = update_payload(st, frame.payload)

        # ── Update byte_diffs deque (needed for rolling byte features in model inference) ──
        raw_bd = payload.get("payload_delta", 0.0)
        if st.byte_diffs is not None:
            st.byte_diffs.append(raw_bd)

        # ── Global CAN-ID entropy (cross-ID, for Fuzzy detection) ─────────────────────────
        self._global_frame_count += 1
        if len(self._recent_can_ids) >= 10 and self._global_frame_count % _ENTROPY_STRIDE == 0:
            counts = Counter(self._recent_can_ids)
            total = len(self._recent_can_ids)
            probs = _np.array([v / total for v in counts.values()])
            self._cached_entropy = float(-_np.sum(probs * _np.log(probs + 1e-12)))
        can_id_entropy = self._cached_entropy

        # ── ML anomaly score from trained IsolationForest ─────────────────────────────────
        ml_norm: float
        vehicle_state: str
        st.ml_frame_count += 1
        if self._models.is_loaded:
            if st.ml_frame_count % _ML_STRIDE == 0:
                features = compute_model_features(st, frame.timestamp, frame.payload, can_id_entropy)
                vehicle_state = self._models.classify_state(features)
                model_score = self._models.score(vehicle_state, features, vehicle=self.vehicle_id)
                if model_score is not None:
                    st.last_ml_norm = min(2.0, max(0.0, model_score))
                else:
                    st.last_ml_norm = min(2.0, max(0.0, update_ml_like(timing, payload)))
                st.last_vehicle_state = vehicle_state
            ml_norm = st.last_ml_norm
            vehicle_state = st.last_vehicle_state
        else:
            # No models loaded — use lightweight heuristic
            ml_norm = min(2.0, max(0.0, update_ml_like(timing, payload)))
            vehicle_state = "unknown"

        # ── Timing anomaly score ──────────────────────────────────────────────────────────
        # DoS fix: timing_std is NEAR ZERO for uniform flooding (consistent 0.5ms intervals).
        # Using only timing_std gives anomaly_score≈0 for DoS — exactly backwards.
        # Fix: also score abnormally HIGH message frequency as a timing anomaly.
        timing_std = timing.get("timing_std", 0.0)
        timing_mean = max(timing.get("timing_mean", 1.0), 1e-6)
        msg_freq = 1.0 / timing_mean  # Hz
        freq_anomaly = max(
            0.0,
            min(1.0, (msg_freq - _FREQ_ANOMALY_LOW_HZ) / (_FREQ_ANOMALY_HIGH_HZ - _FREQ_ANOMALY_LOW_HZ + 1e-6)),
        )
        timing_norm = min(2.0, max(0.0, max(timing_std, freq_anomaly)))

        # ── Payload anomaly score ─────────────────────────────────────────────────────────
        payload_norm = min(2.0, max(0.0, payload.get("continuity", 0.0) + payload.get("entropy_like", 0.0)))

        scored = self.scoring.score(timing_norm, payload_norm, ml_norm)
        st.scores.append(float(scored["fusion_score"]))

        alert = None
        risk_level = str(scored["risk_level"])
        should_emit = float(scored["fusion_score"]) >= self.cfg.alert_threshold and (self.cfg.emit_low_alerts or risk_level != "LOW")
        if should_emit and self.alerts.should_alert(frame.timestamp, frame.can_id, risk_level):
            reason = (
                f"timing={timing_norm:.3f}, payload={payload_norm:.3f}, "
                f"ml={ml_norm:.3f}, persistence={scored['persistence_score']:.3f}, "
                f"freq={msg_freq:.0f}Hz, can_id_entropy={can_id_entropy:.3f}"
            )
            alert = self.alerts.emit(frame.timestamp, frame.can_id, risk_level, float(scored["fusion_score"]), reason)

        return {
            "frame": frame,
            "timing": timing,
            "payload": payload,
            "ml_norm": ml_norm,
            "score": scored,
            "alert": alert,
            "active_can_ids": self.state.active_can_ids(),
            "vehicle_state": vehicle_state,
            "can_id_entropy": can_id_entropy,
        }
