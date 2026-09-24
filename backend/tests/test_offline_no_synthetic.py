"""Generated frames must not enter the live stream during an offline analysis.

The desktop client polls /vehicle throughout an offline analysis. With no CAN
adapter connected that endpoint answers from the synthetic generator, and every
generated frame was appended to live_signals_buffer, which /api/live/signals
serves straight back to the Dashboard's CAN monitor. The monitor therefore
showed identifiers 0x1A2 / 0x3F1 / 0x5D2 / 0x6E7 - none of which appear in any
recording - beside the real results of the file being analysed.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.api import server  # noqa: E402

# The four identifiers the generator rotates through (server.vehicle_snapshot).
GENERATOR_IDS = {"0x1A2", "0x3F1", "0x5D2", "0x6E7"}


@pytest.fixture(autouse=True)
def _clean_state():
    """Each test starts from an idle replay and an empty buffer."""
    previous_state = dict(server.replay_status)
    with server.runtime_lock:
        previous_buffer = list(server.live_signals_buffer)
        server.live_signals_buffer.clear()
    server.replay_status.clear()
    server.replay_status.update({"state": "idle", "input_path": "", "started_at": None})

    yield

    server.replay_status.clear()
    server.replay_status.update(previous_state)
    with server.runtime_lock:
        server.live_signals_buffer.clear()
        server.live_signals_buffer.extend(previous_buffer)


def _poll(times: int = 8) -> None:
    for _ in range(times):
        server.vehicle_snapshot()


def test_generated_frames_are_buffered_when_idle() -> None:
    """The live path is unchanged: with no analysis running the stream fills."""
    _poll()
    with server.runtime_lock:
        assert len(server.live_signals_buffer) > 0
        assert {f["can_id"] for f in server.live_signals_buffer} <= GENERATOR_IDS


@pytest.mark.parametrize("state", ["running", "queued", "starting"])
def test_no_generated_frames_while_a_capture_is_being_analysed(state: str) -> None:
    server.replay_status["state"] = state

    _poll()

    with server.runtime_lock:
        assert server.live_signals_buffer == [], (
            f"generated frames leaked into the live stream while replay state was {state!r}"
        )


def test_an_offline_session_cannot_contaminate_frames_already_captured() -> None:
    """Frames recorded before the analysis stay; nothing generated is added."""
    _poll(4)
    with server.runtime_lock:
        before = list(server.live_signals_buffer)
    assert before, "precondition: the idle poll should have filled the buffer"

    server.replay_status["state"] = "running"
    _poll(10)

    with server.runtime_lock:
        assert server.live_signals_buffer == before


def test_stream_resumes_once_the_analysis_finishes() -> None:
    server.replay_status["state"] = "running"
    _poll(5)
    with server.runtime_lock:
        assert server.live_signals_buffer == []

    server.replay_status["state"] = "completed"
    _poll(5)

    with server.runtime_lock:
        assert len(server.live_signals_buffer) > 0


def test_api_live_signals_returns_nothing_generated_during_analysis() -> None:
    """The endpoint the CAN monitor actually reads."""
    server.replay_status["state"] = "running"
    _poll(10)

    items = server.api_live_signals(limit=200)["items"]

    assert items == []
