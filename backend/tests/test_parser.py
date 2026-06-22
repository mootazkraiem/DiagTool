"""Regression tests for CanLogParser.

Covers: candump-style, ASC-style, CSV-like, comment/blank skipping,
byte column population, source_file tagging.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.data_processing.parser import CanLogParser


CANDUMP_LINES = """\
(1.000000) can0 316#DEADBEEF01020304
(1.001000) can0 329#FF00112233445566
(1.002000) vcan0 7FF#
"""

ASC_LINES = """\
0.001000 1 316 Rx d 8 DE AD BE EF 01 02 03 04
0.002000 1 329 Tx d 4 FF 00 11 22
"""

SHOULD_SKIP = """\
# this is a comment
// another comment
; semicolon comment

"""


def test_candump_parses_frame_count() -> None:
    df, stats = CanLogParser.parse_text(CANDUMP_LINES)
    assert len(df) == 3
    assert stats.lines_parsed == 3
    assert stats.lines_skipped == 0


def test_candump_can_id_correct() -> None:
    df, _ = CanLogParser.parse_text(CANDUMP_LINES)
    assert int(df.iloc[0]["can_id"]) == 0x316


def test_candump_byte_columns_populated() -> None:
    df, _ = CanLogParser.parse_text(CANDUMP_LINES)
    row = df.iloc[0]
    assert row["b0"] == 0xDE
    assert row["b1"] == 0xAD
    assert row["b2"] == 0xBE
    assert row["b3"] == 0xEF


def test_candump_empty_payload_zero_bytes() -> None:
    """CAN ID 7FF# has no data bytes — all bytes should default to 0."""
    df, _ = CanLogParser.parse_text(CANDUMP_LINES)
    empty_row = df[df["can_id"] == 0x7FF].iloc[0]
    for col in [f"b{i}" for i in range(8)]:
        assert empty_row[col] == 0, f"expected b{col[-1]}==0 for empty payload"


def test_asc_parses_correctly() -> None:
    df, stats = CanLogParser.parse_text(ASC_LINES, source_name="test.asc")
    assert len(df) == 2
    assert stats.lines_parsed == 2


def test_asc_byte_values() -> None:
    df, _ = CanLogParser.parse_text(ASC_LINES)
    row = df[df["can_id"] == 0x316].iloc[0]
    assert row["b0"] == 0xDE
    assert row["b7"] == 0x04


def test_comments_and_blanks_skipped() -> None:
    df, stats = CanLogParser.parse_text(SHOULD_SKIP)
    assert len(df) == 0
    assert stats.lines_parsed == 0
    assert stats.lines_skipped == stats.lines_total


def test_source_file_tag() -> None:
    df, _ = CanLogParser.parse_text(CANDUMP_LINES, source_name="mylog.log")
    assert (df["source_file"] == "mylog.log").all()


def test_timestamp_preserved() -> None:
    df, _ = CanLogParser.parse_text(CANDUMP_LINES)
    assert pytest.approx(float(df.iloc[0]["timestamp"])) == 1.0
    assert pytest.approx(float(df.iloc[1]["timestamp"])) == 1.001


def test_mixed_formats_combined() -> None:
    mixed = CANDUMP_LINES + ASC_LINES
    df, stats = CanLogParser.parse_text(mixed)
    assert len(df) == 5
    assert stats.lines_parsed == 5
