"""Signal discovery for the Telemetry channels (backend/decoding/signal_discovery.py).

The DBC manager is replaced by a small fake so each rule can be checked on
frames whose content is known exactly.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from backend.decoding import dbc_manager, signal_discovery as sd


@dataclass
class _Sig:
    name: str
    value: float
    unit: str
    out_of_range: bool = False


class _FakeManager:
    """0x100 carries Vehicle_Speed (byte 0) and a Checksum-like Other_Flag (byte 1, constant);
    0x200 carries HV_Voltage (bytes 2-3, 0xFFFF = not available)."""

    def __init__(self, ids):
        self.ids = ids

    def known_can_ids(self, vehicle_id):
        return list(self.ids) if vehicle_id == "fake_ev" else []

    def decode(self, vehicle_id, can_id, payload):
        if can_id == 0x100:
            return [_Sig("Vehicle_Speed", payload[0], "km/h"), _Sig("Other_Flag", payload[1], "")]
        if can_id == 0x200:
            raw = payload[2] << 8 | payload[3]
            return [_Sig("HV_Voltage", raw / 10, "V", out_of_range=raw == 0xFFFF)]
        return []


def _frames():
    out = []
    for i in range(200):
        t = i * 0.01
        out.append((t, 0x100, (i % 120, 7, 0, 0, 0, 0, 0, 0)))
        volt = 0xFFFF if i % 10 == 0 else 3500 + i
        out.append((t, 0x200, (0, 0, volt >> 8, volt & 0xFF, 0, 0, 0, 0)))
        # 0x300: byte 0 rolling counter, byte 1 constant, byte 2 slow ramp, byte 3 noise-like
        out.append((t, 0x300, (i % 256, 0x55, i // 4, (i * i * 31 + 7) % 256, 0, 0, 0, 0)))
    return out


@pytest.fixture
def fake_dbc(monkeypatch):
    monkeypatch.setattr(dbc_manager, "get_manager", lambda: _FakeManager({0x100, 0x200}))


def test_dbc_path_ranks_priority_groups_and_drops_constant_signals(fake_dbc):
    result = sd.discover(_frames(), "fake_ev", max_channels=4)
    assert result["decoder"] == "dbc"
    labels = [c["label"] for c in result["channels"]]
    assert labels == ["Vehicle_Speed", "HV_Voltage"]          # speed before voltage; constant flag dropped
    assert all(c["decoded"] for c in result["channels"])


def test_dbc_out_of_range_samples_are_excluded(fake_dbc):
    volt = next(c for c in sd.discover(_frames(), "fake_ev")["channels"] if c["label"] == "HV_Voltage")
    assert volt["samples"] == 180                             # 20 "not available" frames left out
    assert volt["max"] < 6553                                 # 0xFFFF / 10 never appears


def test_no_dbc_falls_back_to_raw_bytes_without_counters_or_constants(fake_dbc):
    result = sd.discover(_frames(), "jaguar_ipace", max_channels=12)
    assert result["decoder"] == "raw" and result["dbc_available"] is False
    assert "not decoded" in result["reason"]
    keys = [c["key"] for c in result["channels"]]
    assert "0x300:b0" not in keys                            # rolling counter
    assert "0x300:b1" not in keys                            # constant byte
    assert "0x100:b1" not in keys
    assert keys.index("0x300:b2") < keys.index("0x300:b3")   # smooth ramp before jumpy byte
    assert all(not c["decoded"] and c["unit"] == "raw" for c in result["channels"])


def test_series_are_decimated_to_the_requested_points(fake_dbc):
    ch = sd.discover(_frames(), "jaguar_ipace", points=40)["channels"][0]
    assert len(ch["values"]) == 40 and len(ch["times"]) == 40
    assert ch["samples"] == 200


def test_empty_capture():
    result = sd.discover([], "kia_ev6")
    assert result["decoder"] == "none" and result["channels"] == []


def test_model_id_maps_to_dbc_profile():
    assert sd.profile_id("nissan_leaf_2019") == "nissan_leaf"
    assert sd.profile_id("kia_ev6") == "kia_ev6"
