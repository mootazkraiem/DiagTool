from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from backend.data_processing.decoder import DecodedSignal


@dataclass(frozen=True)
class Anomaly:
    timestamp: float
    severity: str
    title: str
    description: str
    confidence: float
    related_can_id: int
    stream_id: int = 0
    alert_id: str = ""
    occurrences: int = 1
    action_text: str = "ANALYZE"
    source: str = "rule"


class RuleBasedDetector(QObject):
    anomaly_detected = pyqtSignal(object)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._last_seen: Dict[int, Dict[int, float]] = {}
        self._last_values: Dict[int, Dict[int, float]] = {}
        self._last_intervals: Dict[int, Dict[int, float]] = {}

    def process_signal(self, signal: DecodedSignal) -> List[Anomaly]:
        stream_seen = self._last_seen.setdefault(signal.stream_id, {})
        stream_values = self._last_values.setdefault(signal.stream_id, {})
        stream_intervals = self._last_intervals.setdefault(signal.stream_id, {})
        anomalies: List[Anomaly] = []
        timestamp = signal.timestamp
        can_id = signal.can_id

        previous_seen = stream_seen.get(can_id)
        if previous_seen is not None:
            interval = timestamp - previous_seen
            baseline = stream_intervals.get(can_id, interval)
            stream_intervals[can_id] = baseline * 0.75 + interval * 0.25

            if baseline > 0 and abs(interval - baseline) > baseline * 0.55:
                anomalies.append(
                    self._build_anomaly(
                        signal,
                        "warning",
                        "LATENCY_DRIFT_DETECTED",
                        f"{signal.signal_name} interval drifted from {baseline * 1000:.0f} ms to {interval * 1000:.0f} ms.",
                        min(0.96, 0.65 + abs(interval - baseline)),
                    )
                )

            if signal.signal_name == "Engine RPM":
                previous_value = stream_values.get(can_id, signal.value)
                delta = abs(signal.value - previous_value)
                if delta >= 1400:
                    anomalies.append(
                        self._build_anomaly(
                            signal,
                            "warning",
                            "UNEXPECTED_TORQUE_DROP",
                            f"Engine RPM shifted from {previous_value:.0f} to {signal.value:.0f}.",
                            min(0.99, 0.70 + delta / 5000.0),
                        )
                    )

        stream_seen[can_id] = timestamp
        stream_values[can_id] = signal.value

        anomalies.extend(self._threshold_checks(signal))
        anomalies.extend(self._missing_frame_checks(signal.stream_id, timestamp))

        for anomaly in anomalies:
            self.anomaly_detected.emit(anomaly)
        return anomalies

    def _threshold_checks(self, signal: DecodedSignal) -> List[Anomaly]:
        results: List[Anomaly] = []
        if signal.signal_name == "Battery Voltage":
            if signal.value < 320 or signal.value > 420:
                results.append(
                    self._build_anomaly(
                        signal,
                        "critical",
                        "BATTERY_VOLTAGE_OUT_OF_RANGE",
                        f"Battery voltage reached {signal.value:.1f} {signal.unit}.",
                        0.96,
                    )
                )
            elif signal.value < 335 or signal.value > 410:
                results.append(
                    self._build_anomaly(
                        signal,
                        "warning",
                        "BATTERY_VOLTAGE_APPROACHING_LIMIT",
                        f"Battery voltage is trending near limits at {signal.value:.1f} {signal.unit}.",
                        0.78,
                    )
                )
        if signal.signal_name in {"Motor Temperature", "Inverter Temperature"} and (signal.value <= -50 or signal.value >= 95):
            if signal.value <= -50 or signal.value >= 120:
                severity = "critical"
            elif signal.value >= 105:
                severity = "critical"
            else:
                severity = "warning"
            results.append(
                self._build_anomaly(
                    signal,
                    severity,
                    "MOTOR_TEMPERATURE_HIGH" if signal.signal_name == "Motor Temperature" else "INVERTER_TEMPERATURE_HIGH",
                    f"{signal.signal_name} is {signal.value:.1f} {signal.unit}.",
                    0.88 if severity == "critical" else 0.76,
                )
            )
        return results

    def _missing_frame_checks(self, stream_id: int, timestamp: float) -> List[Anomaly]:
        results: List[Anomaly] = []
        for can_id, last_seen in list(self._last_seen.get(stream_id, {}).items()):
            if timestamp - last_seen > 0.5:
                results.append(
                    Anomaly(
                        timestamp=timestamp,
                        severity="warning",
                        title="MISSING_CAN_FRAME",
                        description=f"No frame received from CAN ID 0x{can_id:X} for more than 500 ms.",
                        confidence=0.84,
                        related_can_id=can_id,
                        stream_id=stream_id,
                        alert_id=f"{stream_id}:MISSING_CAN_FRAME:{can_id}",
                        action_text="ANALYZE",
                        source="rule",
                    )
                )
        return results

    def _build_anomaly(
        self,
        signal: DecodedSignal,
        severity: str,
        title: str,
        description: str,
        confidence: float,
    ) -> Anomaly:
        return Anomaly(
            timestamp=signal.timestamp,
            severity=severity,
            title=title,
            description=description,
            confidence=confidence,
            related_can_id=signal.can_id,
            stream_id=signal.stream_id,
            alert_id=f"{signal.stream_id}:{title}:{signal.can_id}",
            action_text="ANALYZE",
            source="rule",
        )
