"""Regression tests for the alert grouper / incident engine.

Covers: empty input, single alert, grouping within window,
splitting at window boundary, severity classification,
dominant pattern selection, and response generation.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.ml.alert_grouper import GROUPING_WINDOW_SEC, group


def _alert(can_id: str, timestamp: float, score: float = 0.3, pattern: str = "normal") -> dict:
    return {
        "can_id": can_id,
        "timestamp": timestamp,
        "anomaly_score": score,
        "temporal_pattern": pattern,
        "plausibility_passed": True,
        "timing_anomaly": False,
        "kb_match": "",
    }


def test_empty_input_returns_empty_list() -> None:
    assert group([]) == []


def test_single_alert_produces_one_incident() -> None:
    incidents = group([_alert("0x316", 1.0, score=0.6)])
    assert len(incidents) == 1
    inc = incidents[0]
    assert inc["can_id"] == "0x316"
    assert inc["frame_count"] == 1


def test_alerts_within_window_merged() -> None:
    alerts = [
        _alert("0x316", 1.0),
        _alert("0x316", 1.5),
        _alert("0x316", 2.0),
    ]
    incidents = group(alerts, window_sec=2.0)
    assert len(incidents) == 1
    assert incidents[0]["frame_count"] == 3


def test_alerts_split_at_window_boundary() -> None:
    window = GROUPING_WINDOW_SEC
    alerts = [
        _alert("0x316", 0.0),
        _alert("0x316", window + 0.1),  # outside window — opens new incident
    ]
    incidents = group(alerts)
    assert len(incidents) == 2


def test_different_can_ids_produce_separate_incidents() -> None:
    alerts = [
        _alert("0x316", 1.0),
        _alert("0x329", 1.0),
        _alert("0x316", 1.5),
    ]
    incidents = group(alerts)
    can_ids = {i["can_id"] for i in incidents}
    assert "0x316" in can_ids
    assert "0x329" in can_ids


def test_peak_score_is_maximum() -> None:
    alerts = [
        _alert("0x316", 1.0, score=0.3),
        _alert("0x316", 1.2, score=0.9),
        _alert("0x316", 1.4, score=0.5),
    ]
    incidents = group(alerts)
    assert len(incidents) == 1
    assert pytest.approx(incidents[0]["peak_score"]) == 0.9


def test_critical_severity_on_high_score() -> None:
    alerts = [_alert("0x316", 1.0, score=0.8)]
    incidents = group(alerts)
    assert incidents[0]["severity"] == "CRITICAL"


def test_warning_severity_on_low_score() -> None:
    alerts = [_alert("0x316", 1.0, score=0.2)]
    incidents = group(alerts)
    assert incidents[0]["severity"] == "WARNING"


def test_incident_has_recommended_response() -> None:
    alerts = [_alert("0x316", 1.0, score=0.8)]
    incidents = group(alerts)
    assert "recommended_response" in incidents[0]
    assert len(incidents[0]["recommended_response"]) > 10


def test_dominant_pattern_from_temporal_field() -> None:
    alerts = [
        _alert("0x316", 1.0, pattern="dos_burst"),
        _alert("0x316", 1.1, pattern="dos_burst"),
        _alert("0x316", 1.2, pattern="rate_spike"),
    ]
    incidents = group(alerts)
    assert incidents[0]["dominant_pattern"] == "dos_burst"


def test_first_seen_last_seen_timestamps() -> None:
    alerts = [
        _alert("0x316", 5.0),
        _alert("0x316", 5.5),
        _alert("0x316", 6.0),
    ]
    incidents = group(alerts)
    inc = incidents[0]
    assert pytest.approx(inc["first_seen"]) == 5.0
    assert pytest.approx(inc["last_seen"]) == 6.0


def test_incident_id_is_string() -> None:
    incidents = group([_alert("0x316", 1.0)])
    assert isinstance(incidents[0]["incident_id"], str)
    assert len(incidents[0]["incident_id"]) > 0
