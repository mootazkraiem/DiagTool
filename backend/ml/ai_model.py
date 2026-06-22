from __future__ import annotations

import pickle
from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from backend.ml.anomaly import Anomaly
from backend.data_processing.decoder import DecodedSignal

try:
    from sklearn.ensemble import IsolationForest
except ImportError:  # pragma: no cover - optional dependency at runtime
    IsolationForest = None


class AIModel(QObject):
    anomaly_detected = pyqtSignal(object)
    model_status = pyqtSignal(str)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._model_path = Path(__file__).resolve().with_name("ai_model.pkl")
        self._samples: List[List[float]] = []
        self._model = None
        self._last_timestamp_by_id = {}
        self._last_value_by_id = {}
        self._warmup_size = 64
        self._threshold = -0.16
        self._load_model()

    def process_signal(self, signal: DecodedSignal) -> Optional[Anomaly]:
        if not signal or signal.timestamp <= 0:
            return None

        features = self._features_for(signal)
        if features is None:
            return None

        if self._model is None:
            self._samples.append(features)
            if len(self._samples) >= self._warmup_size:
                self.train(self._samples)
            return None

        if IsolationForest is None:
            return None

        score = float(self._model.decision_function([features])[0])
        if score >= self._threshold:
            return None

        anomaly = Anomaly(
            timestamp=signal.timestamp,
            severity="warning" if score > self._threshold - 0.05 else "critical",
            title="AI_PATTERN_ANOMALY",
            description=f"IsolationForest flagged {signal.signal_name} as atypical (score {score:.3f}).",
            confidence=min(0.99, max(0.55, 0.5 + abs(score))),
            related_can_id=signal.can_id,
            stream_id=signal.stream_id,
            alert_id=f"{signal.stream_id}:AI_PATTERN_ANOMALY:{signal.can_id}:{signal.signal_name}",
            action_text="ANALYZE",
            source="ai",
        )
        self.anomaly_detected.emit(anomaly)
        return anomaly

    def train(self, samples: List[List[float]]):
        if IsolationForest is None or not samples:
            self.model_status.emit("AI model unavailable: scikit-learn not installed")
            return
        model = IsolationForest(
            contamination=0.08,
            n_estimators=120,
            random_state=42,
        )
        model.fit(samples)
        self._model = model
        self._save_model()
        self.model_status.emit("AI model trained")

    def _features_for(self, signal: DecodedSignal) -> Optional[List[float]]:
        last_ts = self._last_timestamp_by_id.get(signal.can_id, signal.timestamp)
        last_value = self._last_value_by_id.get(signal.can_id, signal.value)
        delta_t = max(0.0, signal.timestamp - last_ts)
        delta_value = signal.value - last_value

        self._last_timestamp_by_id[signal.can_id] = signal.timestamp
        self._last_value_by_id[signal.can_id] = signal.value
        severity_num = {"normal": 0.0, "warning": 0.5, "critical": 1.0}.get(signal.severity, 0.0)

        return [
            float(signal.can_id),
            float(signal.value),
            float(delta_t),
            float(delta_value),
            severity_num,
        ]

    def _load_model(self):
        if not self._model_path.exists():
            self.model_status.emit("AI model warmup")
            return
        try:
            with self._model_path.open("rb") as handle:
                self._model = pickle.load(handle)
            self.model_status.emit("AI model loaded")
        except Exception:
            self._model = None
            self.model_status.emit("AI model warmup")

    def _save_model(self):
        if self._model is None:
            return
        try:
            with self._model_path.open("wb") as handle:
                pickle.dump(self._model, handle)
        except Exception:
            pass
