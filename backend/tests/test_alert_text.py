"""Alert explanation text: baseline ratio and per-alert response action."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.ml.alert_grouper import group as group_alerts
from backend.ml.temporal import summarize_anomaly


def test_dos_ratio_uses_a_real_baseline():
    out = summarize_anomaly("0x100", "dos_burst", 1.0, {"0x100": 10.0}, current_freq=50.0)
    assert "5.0× above baseline" in out["detail"]


def test_dos_with_a_near_silent_baseline_has_no_ratio():
    # A baseline of ~0 msg/s used to print ratios like 2.57e+17x.
    out = summarize_anomaly("0x17FC00B9", "dos_burst", 1.0, {"0x17FC00B9": 1.5e-16}, current_freq=39.0)
    assert "above baseline" not in out["detail"]
    assert "e+" not in out["detail"]
    assert "essentially silent in the baseline" in out["detail"]


def test_each_alert_maps_to_the_incident_spanning_its_time():
    # Two separate incidents on the same CAN ID: a DoS burst early, a quiet alert later.
    alerts = [
        {"can_id": "0x7B", "timestamp": t, "anomaly_score": 0.95, "temporal_pattern": "dos_burst"}
        for t in (1.0, 1.1, 1.2)
    ] + [{"can_id": "0x7B", "timestamp": 100.0, "anomaly_score": 0.6, "temporal_pattern": "normal"}]
    incidents = group_alerts(alerts)
    assert len(incidents) == 2
    late = [i for i in incidents if i["first_seen"] <= 100.0 <= i["last_seen"]]
    assert len(late) == 1
    assert "ISOLATE" not in late[0]["recommended_response"]
