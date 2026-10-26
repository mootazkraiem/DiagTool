"""The Arduino bench rig as a vehicle profile with its own, complete DBC.

The rig (arduino_bench_rig/) sends 0x316 (speed, 60 km/h), 0x3F9 (state of
charge, 78 %) and, on purpose, 0x666, which its DBC leaves out. Live capture
must decode the first two with the rig's DBC, not with the cross-vehicle signal
map (which reads them as Hyundai messages), and must flag 0x666 as soon as it
arrives: live capture has no learning window, the complete DBC is the list of
allowed identifiers. Frames go through python-can's virtual bus, so no hardware
and no running backend are needed.
"""
from __future__ import annotations

import contextlib
import io
import os
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ["GOOGLE_API_KEY"] = ""

from backend.decoding.dbc_manager import DBCManager
from backend.hardware.can_interface import CanHardwareReader, _complete_dbc_ids

SPEED = [60, 0, 0, 0, 0, 0, 0, 0]
SOC = [78, 0, 0, 0, 0, 0, 0, 0]
ODD = [0xDE, 0xAD, 0xBE, 0xEF, 0, 0, 0, 0]


def test_rig_dbc_decodes_speed_and_state_of_charge() -> None:
    mgr = DBCManager()
    [speed] = mgr.decode("bench_rig", 0x316, SPEED)
    [soc] = mgr.decode("bench_rig", 0x3F9, SOC)
    assert (speed.name, speed.value, speed.unit, speed.system) == ("Vehicle_Speed", 60.0, "km/h", "Vehicle")
    assert (soc.name, soc.value, soc.unit, soc.system) == ("State_Of_Charge", 78.0, "%", "Battery")
    assert mgr.decode("bench_rig", 0x666, ODD) == []


def test_only_the_rig_profile_declares_a_complete_dbc() -> None:
    assert _complete_dbc_ids("bench_rig") == frozenset({0x316, 0x3F9})
    for vid in ("kia_ev6", "nissan_leaf", "bmw_i3", "general", "", "no_such_vehicle"):
        assert _complete_dbc_ids(vid) is None, vid


def test_rig_profile_scores_with_the_general_model() -> None:
    from backend.ml.runtime.model_status import resolve
    st = resolve("bench_rig")
    assert (st.status, st.offline, st.live) == ("general", "general", "general")


class _Stats:
    def __init__(self) -> None:
        self.alerts: list[dict] = []

    def on_frame(self) -> None: ...
    def on_score(self, score: float) -> None: ...
    def on_alert(self, alert: dict) -> None:
        self.alerts.append(alert)


def _live_engine(vid: str):
    from backend.ml.runtime.model_status import live_engine
    with contextlib.redirect_stdout(io.StringIO()):
        return live_engine(vid)


@pytest.fixture()
def rig():
    """A reader connected to a virtual bus as the bench rig, and a sender on the same bus."""
    can = pytest.importorskip("can")
    signals: list[dict] = []
    alerts: list[dict] = []
    stats = _Stats()
    reader = CanHardwareReader(None, stats, signals, alerts, threading.Lock(), engine_factory=_live_engine)
    reader.connect("virtual", channel="bench_rig_test", vehicle_id="bench_rig")
    sender = can.interface.Bus(interface="virtual", channel="bench_rig_test")

    def send(can_id: int, data: list[int]) -> None:
        sender.send(can.Message(arbitration_id=can_id, data=bytes(data), is_extended_id=False))

    def wait_for(n: int) -> None:
        deadline = time.time() + 10
        while reader.frames_received < n and time.time() < deadline:
            time.sleep(0.02)
        assert reader.frames_received >= n, f"only {reader.frames_received} of {n} frames were read"

    try:
        yield reader, signals, alerts, stats, send, wait_for
    finally:
        sender.shutdown()
        reader.disconnect()


def test_live_rig_frames_are_decoded_with_the_rig_dbc(rig) -> None:
    reader, signals, alerts, _, send, wait_for = rig
    send(0x316, SPEED)
    send(0x3F9, SOC)
    wait_for(2)
    by_id = {s["can_id"]: s["signals"] for s in signals}
    assert [(x["name"], x["value"], x["unit"]) for x in by_id["0x316"]] == [("Vehicle_Speed", 60.0, "km/h")]
    assert [(x["name"], x["value"], x["unit"]) for x in by_id["0x3F9"]] == [("State_Of_Charge", 78.0, "%")]
    assert not [a for a in alerts if a["dominant_detection_layer"] == "whitelist"]


def test_live_rig_flags_0x666_on_its_first_frame(rig) -> None:
    reader, signals, alerts, stats, send, wait_for = rig
    send(0x316, SPEED)
    send(0x666, ODD)
    send(0x666, ODD)          # inside the one second cooldown: no second alert
    wait_for(3)
    flagged = [a for a in alerts if a["can_id"] == "0x666"]
    assert len(flagged) == 1
    a = flagged[0]
    assert a["dominant_detection_layer"] == "whitelist"
    assert a["attack_type"] == "unknown_identifier"
    assert a["score"] >= 0.95 and a["severity"] in ("HIGH", "CRITICAL")
    assert "not defined in the DBC of the Arduino bench rig profile" in a["reason"]
    assert [x for x in signals if x["can_id"] == "0x666"][0]["signals"] == []
    assert any(int(x["can_id"]) == 0x666 for x in stats.alerts)
    assert reader.alert_count == len(alerts)


def test_a_partial_dbc_profile_never_flags_unknown_identifiers() -> None:
    can = pytest.importorskip("can")
    alerts: list[dict] = []
    reader = CanHardwareReader(None, _Stats(), [], alerts, threading.Lock(), engine_factory=_live_engine)
    reader.connect("virtual", channel="partial_dbc_test", vehicle_id="renault_zoe")
    sender = can.interface.Bus(interface="virtual", channel="partial_dbc_test")
    try:
        sender.send(can.Message(arbitration_id=0x666, data=bytes(ODD), is_extended_id=False))
        deadline = time.time() + 10
        while reader.frames_received < 1 and time.time() < deadline:
            time.sleep(0.02)
        assert reader.frames_received == 1
        assert not [a for a in alerts if a["dominant_detection_layer"] == "whitelist"]
    finally:
        sender.shutdown()
        reader.disconnect()


def test_decoded_signals_endpoint_keeps_the_profile_decoding() -> None:
    import backend.api.server as server

    rig_frame = {"can_id": "0x316", **{f"b{i}": v for i, v in enumerate(SPEED)},
                 "signals": [{"name": "Vehicle_Speed", "value": 60.0, "unit": "km/h",
                              "out_of_range": False, "system": "Vehicle"}]}
    saved = list(server.live_signals_buffer)
    with server.runtime_lock:
        server.live_signals_buffer[:] = [rig_frame]
    try:
        items = server.api_live_decoded_signals()["items"]
    finally:
        with server.runtime_lock:
            server.live_signals_buffer[:] = saved
    assert [(i["name"], i["value"], i["unit"], i["can_id"]) for i in items] == [("Vehicle_Speed", 60.0, "km/h", "0x316")]


def test_live_snapshot_carries_the_rig_speed_and_state_of_charge() -> None:
    """The /vehicle snapshot the Dashboard and Telemetry read maps the rig's
    decoded signals to VehicleSpeed and SOC."""
    import backend.api.server as server

    def frame(can_id: str, data: list[int], name: str, value: float, unit: str) -> dict:
        return {"can_id": can_id, "anomaly_score": 0.1, **{f"b{i}": v for i, v in enumerate(data)},
                "signals": [{"name": name, "value": value, "unit": unit, "out_of_range": False, "system": ""}]}

    saved = list(server.live_signals_buffer)
    saved_fields = dict(server._hw_last_snapshot_fields)
    server._hw_last_snapshot_fields.clear()
    try:
        for f in (frame("0x316", SPEED, "Vehicle_Speed", 60.0, "km/h"),
                  frame("0x3F9", SOC, "State_Of_Charge", 78.0, "%")):
            with server.runtime_lock:
                server.live_signals_buffer[:] = [f]
            snap = server._vehicle_snapshot_from_hardware()
    finally:
        with server.runtime_lock:
            server.live_signals_buffer[:] = saved
        server._hw_last_snapshot_fields.clear()
        server._hw_last_snapshot_fields.update(saved_fields)
    assert (snap["VehicleSpeed"], snap["SOC"], snap["battery"]) == (60.0, 78.0, 78)


def test_decoded_signals_endpoint_still_uses_the_signal_map_without_profile_decoding() -> None:
    import backend.api.server as server

    frame = {"can_id": "0x316", **{f"b{i}": v for i, v in enumerate(SPEED)}}   # simulator frame, no "signals"
    saved = list(server.live_signals_buffer)
    with server.runtime_lock:
        server.live_signals_buffer[:] = [frame]
    try:
        names = {i["name"] for i in server.api_live_decoded_signals()["items"]}
    finally:
        with server.runtime_lock:
            server.live_signals_buffer[:] = saved
    assert names and "Vehicle_Speed" not in names
