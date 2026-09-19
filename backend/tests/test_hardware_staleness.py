"""Regression tests for CanHardwareReader's connection-staleness detection.

Covers the bug found during real hardware bring-up: a silently unplugged
adapter never raises an exception (recv() just times out forever), so
exception-only detection left is_connected reporting True indefinitely.
is_connected is now a computed property requiring both a "link up" flag
and a recent last_frame_at — these tests exercise that property directly,
plus the buffer-clearing behaviour on disconnect(), without touching any
real hardware.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.hardware.can_interface import CanHardwareReader, _STALE_AFTER_SECONDS


class _FakeEngine:
    vehicle_id: str = "general"


class _FakeStats:
    def on_frame(self) -> None: ...
    def on_score(self, score: float) -> None: ...
    def on_alert(self, alert: dict) -> None: ...


def _make_reader() -> CanHardwareReader:
    return CanHardwareReader(
        runtime_engine=_FakeEngine(),
        runtime_stats=_FakeStats(),
        signals_buffer=[],
        alerts_buffer=[],
        lock=threading.Lock(),
    )


def test_freshly_constructed_reader_is_not_connected() -> None:
    reader = _make_reader()
    assert reader.is_connected is False


def test_link_up_with_no_frames_yet_uses_connected_at_grace_period() -> None:
    reader = _make_reader()
    reader._link_up = True
    reader.connected_at = time.time()
    # No frame has arrived yet, but we just connected — should not be
    # treated as stale immediately.
    assert reader.is_connected is True


def test_link_up_with_recent_frame_is_connected() -> None:
    reader = _make_reader()
    reader._link_up = True
    reader.connected_at = time.time() - 100
    reader.last_frame_at = time.time()
    assert reader.is_connected is True


def test_link_up_with_old_frame_is_stale_not_connected() -> None:
    """This is the exact bug from the 4-hour-offline incident: link stays
    up, but nothing has arrived in far longer than any real bus would ever
    go quiet — must report disconnected."""
    reader = _make_reader()
    reader._link_up = True
    reader.connected_at = time.time() - 10_000
    reader.last_frame_at = time.time() - (_STALE_AFTER_SECONDS + 1)
    assert reader.is_connected is False


def test_link_down_is_never_connected_even_with_fresh_frame_timestamp() -> None:
    reader = _make_reader()
    reader._link_up = False
    reader.last_frame_at = time.time()
    assert reader.is_connected is False


def test_status_reports_stale_flag_distinct_from_is_connected() -> None:
    reader = _make_reader()
    reader._link_up = True
    reader.connected_at = time.time() - 10_000
    reader.last_frame_at = time.time() - (_STALE_AFTER_SECONDS + 1)
    status = reader.status()
    assert status["is_connected"] is False
    assert status["link_up"] is True
    assert status["stale"] is True
    assert status["seconds_since_last_frame"] >= _STALE_AFTER_SECONDS


def test_disconnect_clears_shared_buffers() -> None:
    signals: list[dict] = [{"can_id": "0x316"}]
    alerts: list[dict] = [{"can_id": "0x666"}]
    reader = CanHardwareReader(
        runtime_engine=_FakeEngine(),
        runtime_stats=_FakeStats(),
        signals_buffer=signals,
        alerts_buffer=alerts,
        lock=threading.Lock(),
    )
    reader._link_up = True

    reader.disconnect()

    assert signals == []
    assert alerts == []
    assert reader.is_connected is False
    assert reader.last_frame_at is None
