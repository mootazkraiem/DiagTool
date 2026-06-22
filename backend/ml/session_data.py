from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from typing import DefaultDict, Dict, List, Optional, Set

from PyQt6.QtCore import QObject, pyqtSignal

from backend.ml.anomaly import Anomaly
from backend.data_processing.decoder import DecodedSignal


class SessionDataManager(QObject):
    signal_added = pyqtSignal(object)
    anomaly_updated = pyqtSignal(object)
    anomaly_ignored = pyqtSignal(str)
    session_started = pyqtSignal(int)
    session_cleared = pyqtSignal(int)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        # Stream-scoped state keeps old sessions isolated from new ones.
        self.current_stream_id = 0
        self.signal_history: DefaultDict[int, DefaultDict[str, List[DecodedSignal]]] = defaultdict(lambda: defaultdict(list))
        self.latest_signals: DefaultDict[int, Dict[str, DecodedSignal]] = defaultdict(dict)
        self.active_anomalies: DefaultDict[int, Dict[str, Anomaly]] = defaultdict(dict)
        self.ignored_alerts: DefaultDict[int, Set[str]] = defaultdict(set)

    def start_session(self, keep_previous: bool = False) -> int:
        self.current_stream_id += 1
        if not keep_previous:
            self.clear_all()
        self.session_started.emit(self.current_stream_id)
        return self.current_stream_id

    def add_signal(self, decoded_signal: DecodedSignal):
        stream_id = decoded_signal.stream_id or self.current_stream_id
        self.current_stream_id = max(self.current_stream_id, stream_id)
        self.signal_history[stream_id][decoded_signal.signal_name].append(decoded_signal)
        self.latest_signals[stream_id][decoded_signal.signal_name] = decoded_signal
        self.signal_added.emit(decoded_signal)

    def upsert_anomaly(self, anomaly: Anomaly):
        stream_id = anomaly.stream_id or self.current_stream_id
        if anomaly.alert_id in self.ignored_alerts[stream_id]:
            return

        existing = self.active_anomalies[stream_id].get(anomaly.alert_id)
        if existing is not None:
            anomaly = replace(
                anomaly,
                timestamp=anomaly.timestamp,
                confidence=max(existing.confidence, anomaly.confidence),
                occurrences=existing.occurrences + 1,
            )
        self.active_anomalies[stream_id][anomaly.alert_id] = anomaly
        self.anomaly_updated.emit(anomaly)

    def ignore_anomaly(self, alert_id: str, stream_id: Optional[int] = None):
        stream_id = stream_id or self.current_stream_id
        self.ignored_alerts[stream_id].add(alert_id)
        self.active_anomalies[stream_id].pop(alert_id, None)
        self.anomaly_ignored.emit(alert_id)

    def get_signal_history(self, signal_name: str, stream_id: Optional[int] = None) -> List[DecodedSignal]:
        stream_id = stream_id or self.current_stream_id
        return list(self.signal_history.get(stream_id, {}).get(signal_name, []))

    def get_all_signals(self, stream_id: Optional[int] = None) -> List[DecodedSignal]:
        stream_id = stream_id or self.current_stream_id
        combined: List[DecodedSignal] = []
        for signals in self.signal_history.get(stream_id, {}).values():
            combined.extend(signals)
        combined.sort(key=lambda item: (item.timestamp, item.can_id, item.frame_key))
        return combined

    def get_signal_names(self, stream_id: Optional[int] = None) -> List[str]:
        stream_id = stream_id or self.current_stream_id
        return sorted(self.signal_history.get(stream_id, {}).keys())

    def get_latest_values(self, stream_id: Optional[int] = None) -> Dict[str, DecodedSignal]:
        stream_id = stream_id or self.current_stream_id
        return dict(self.latest_signals.get(stream_id, {}))

    def get_active_anomalies(self, stream_id: Optional[int] = None) -> List[Anomaly]:
        stream_id = stream_id or self.current_stream_id
        anomalies = list(self.active_anomalies.get(stream_id, {}).values())
        anomalies.sort(key=lambda item: item.timestamp, reverse=True)
        return anomalies

    def clear_session(self, stream_id: Optional[int] = None):
        stream_id = stream_id or self.current_stream_id
        self.signal_history.pop(stream_id, None)
        self.latest_signals.pop(stream_id, None)
        self.active_anomalies.pop(stream_id, None)
        self.ignored_alerts.pop(stream_id, None)
        self.session_cleared.emit(stream_id)

    def clear_all(self):
        self.signal_history.clear()
        self.latest_signals.clear()
        self.active_anomalies.clear()
        self.ignored_alerts.clear()
