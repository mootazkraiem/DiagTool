"""Regression tests for the /analyze CSV fallback (backend.data_processing.csv_frames).

Expected values are read independently from the raw files, so the parser is
checked against the source data rather than against its own output.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.data_processing.csv_frames import parse_csv_frames  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SKODA = ROOT / "assets" / "Skoda Enyaq" / "file_16.csv"
BYD = ROOT / "assets" / "EV-CANlogs-main" / "BYD Atto 3" / "CAN run 15sec with 12D-50ms & 441-100ms.csv"
OUTLANDER = ROOT / "assets" / "EV-CANlogs-main" / "Mitshubishi Outlander" / "outlander-2016-heater.csv"
REPLAY = ROOT / "backend" / "ml" / "outputs" / "replay_logs" / "normal.csv"

SKODA_ID_COUNTS = {
    402522235: 4178, 402391163: 3798, 2001: 3779, 1862: 1516, 1968: 1516,
    1895: 1516, 402391225: 760, 402522297: 760, 402391158: 758, 402522230: 758,
}


def _parse(path: Path):
    return parse_csv_frames(path.read_bytes(), path.name)


def _raw_column(path: Path, suffix: str) -> list[str]:
    lines = [l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    header = lines[0].split(",")
    column = next(i for i, h in enumerate(header) if h.endswith(suffix))
    return [l.split(",")[column].strip() for l in lines[1:]]


# ── asammdf MF4 export ───────────────────────────────────────────────────────

def test_mf4_export_uses_id_column_not_bus_channel() -> None:
    df = _parse(SKODA)
    assert len(df) == 19339
    assert (df["can_id"] != 1).all(), "BusChannel (always 1) must not be read as the CAN ID"
    assert dict(Counter(df["can_id"].tolist())) == SKODA_ID_COUNTS


def test_mf4_export_ids_match_raw_id_column_row_by_row() -> None:
    df = _parse(SKODA)
    assert df["can_id"].tolist() == [int(v) for v in _raw_column(SKODA, ".ID")]


def test_mf4_export_payload_comes_from_databytes_row_by_row() -> None:
    df = _parse(SKODA)
    raw = _raw_column(SKODA, ".DataBytes")
    for i, cell in enumerate(raw):
        expected = [int(t) for t in cell.strip("[]").split()]
        expected = (expected + [0] * 8)[:8]
        assert df.iloc[i][[f"b{k}" for k in range(8)]].tolist() == expected
    assert df.iloc[0][[f"b{k}" for k in range(8)]].tolist() == [3, 34, 70, 91, 85, 85, 85, 85]
    assert df.iloc[1][[f"b{k}" for k in range(8)]].tolist() == [5, 98, 70, 91, 2, 22, 170, 170]


# ── SavvyCAN exports ─────────────────────────────────────────────────────────

def test_savvycan_hex_ids_and_bytes_row_by_row() -> None:
    df = _parse(BYD)
    lines = [l for l in BYD.read_text(encoding="utf-8").splitlines()[1:] if l.strip()]
    assert len(df) == len(lines)
    for i, line in enumerate(lines):
        f = line.split(",")
        length = int(f[5])
        expected = ([int(f[6 + k], 16) for k in range(length)] + [0] * 8)[:8]
        assert df.iloc[i]["can_id"] == int(f[1], 16)
        assert df.iloc[i][[f"b{k}" for k in range(8)]].tolist() == expected


def test_savvycan_without_dir_column() -> None:
    df = _parse(OUTLANDER)
    assert df.iloc[0]["can_id"] == 0x75A
    assert df.iloc[0][[f"b{k}" for k in range(8)]].tolist() == [0x03, 0xE8, 0x03, 0xE8, 0x64, 0x64, 0x38, 0x39]


# ── timestamp,can_id,b0..b7 ──────────────────────────────────────────────────

def test_replay_csv_keeps_hex_id_semantics_and_valid_bytes() -> None:
    df = _parse(REPLAY)
    # No hex evidence in "260,316,329,545": the previous hex reading is kept.
    assert sorted(df["can_id"].unique().tolist()) == [0x260, 0x316, 0x329, 0x545]
    # Byte columns contain "128": decimal by evidence. The previous per-value
    # hex-first parse produced 0x128 = 296, an impossible byte.
    assert df.iloc[0][[f"b{k}" for k in range(8)]].tolist() == [0, 128, 0, 51, 0, 80, 5, 0]
    assert int(df[[f"b{k}" for k in range(8)]].max().max()) <= 255


def test_headerless_csv_keeps_previous_behaviour() -> None:
    df = parse_csv_frames(b"0.1,1A0,DE,AD,BE,EF,01,02,03,04\n0.2,7DF,02,01,00,00,00,00,00,00\n", "h.csv")
    assert df["can_id"].tolist() == [0x1A0, 0x7DF]
    assert df.iloc[0][[f"b{k}" for k in range(8)]].tolist() == [0xDE, 0xAD, 0xBE, 0xEF, 1, 2, 3, 4]
