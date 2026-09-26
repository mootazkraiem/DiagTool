"""Regression tests for the /analyze CSV fallback (backend.data_processing.csv_frames).

Expected values are read independently from the raw files, so the parser is
checked against the source data rather than against its own output.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import pandas as pd
import pytest

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


def test_savvycan_timestamps_are_microseconds_converted_to_seconds() -> None:
    """SavvyCAN "Time Stamp" is microseconds; the parser returns seconds (Step 12, P0-1)."""
    from backend.data_processing.csv_frames import parse_csv_frames

    text = ("Time Stamp,ID,Extended,Dir,Bus,LEN,D1,D2,D3,D4,D5,D6,D7,D8\n"
            "12720014,0000014C,false,Rx,0,8,00,00,10,68,0F,1A,0F,25,\n"
            "12720634,000000A3,false,Rx,0,8,B2,06,00,00,00,00,00,00,\n"
            "12720651,00000066,false,Rx,0,8,00,00,00,00,00,00,00,00,\n")
    df = parse_csv_frames(text.encode(), "jaguar.csv")
    assert df["timestamp"].tolist() == [12720014 / 1e6, 12720634 / 1e6, 12720651 / 1e6]
    assert df["timestamp"].diff().iloc[1:].round(9).tolist() == [0.00062, 0.000017]


def test_non_savvycan_csv_keeps_seconds() -> None:
    from backend.data_processing.csv_frames import parse_csv_frames

    df = parse_csv_frames(b"timestamp,can_id,b0,b1,b2,b3,b4,b5,b6,b7\n12.5,1A0,1,2,3,4,5,6,7,8\n", "x.csv")
    assert df["timestamp"].tolist() == [12.5]
    df = parse_csv_frames(b"Time,ID,D1,D2\n3.25,1A0,01,02\n", "y.csv")      # D-columns without "Time Stamp"
    assert df["timestamp"].tolist() == [3.25]


JAGUAR = ROOT / "assets" / "EV-CANlogs-main" / "Jaguar IPACE"


@pytest.mark.skipif(not JAGUAR.is_dir(), reason="Jaguar recordings not present")
def test_savvycan_frames_are_identical_to_the_training_loader() -> None:
    """Timestamps, IDs and payloads the app parses equal what the models were trained on."""
    from backend.data_processing.csv_frames import parse_csv_frames
    from backend.ml.training import recordings as rec

    for path in sorted(JAGUAR.glob("*.csv")):
        app = parse_csv_frames(path.read_bytes(), path.name)
        trained = rec.load_recording(rec.Recording("jaguar_ipace", path, "savvycan_csv"))
        cols = ["timestamp", "can_id", *[f"b{k}" for k in range(8)]]
        pd.testing.assert_frame_equal(app[cols].reset_index(drop=True), trained.reset_index(drop=True),
                                      check_dtype=False, rtol=0, atol=0)


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


# ── canonical MF4-converter output is decimal ────────────────────────────────
#
# The converter writes can_id via int(float(text)), so 2028 is decimal (UDS
# response 0x7EC), not hex 0x2028. Values like 2028/2020/25 are valid hex that
# stay inside MAX_CAN_ID, so nothing in the data contradicts a hex reading and
# the default decides. Matching is on the exact ten-column canonical header:
# replay logs add state/attack_type and stay hex (test above).

CANONICAL_MF4 = (
    b"timestamp,can_id,b0,b1,b2,b3,b4,b5,b6,b7\n"
    b"0.0,2028,16,62,98,1,1,239,251,231\n"
    b"0.25,2020,3,34,1,1,170,170,170,170\n"
    b"0.50,25,15,36,176,201,0,238,79,127\n"
    b"0.75,5,111,227,180,6,111,227,180,6\n"
)


def test_canonical_mf4_header_reads_ids_as_decimal() -> None:
    df = parse_csv_frames(CANONICAL_MF4, "converted.csv")
    assert df["can_id"].tolist() == [0x7EC, 0x7E4, 0x19, 0x5]
    assert [f"0x{v:X}" for v in df["can_id"]] == ["0x7EC", "0x7E4", "0x19", "0x5"]


def test_canonical_mf4_payload_bytes_are_decimal() -> None:
    df = parse_csv_frames(CANONICAL_MF4, "converted.csv")
    assert df.iloc[0][[f"b{k}" for k in range(8)]].tolist() == [16, 62, 98, 1, 1, 239, 251, 231]
    assert df.iloc[3][[f"b{k}" for k in range(8)]].tolist() == [111, 227, 180, 6, 111, 227, 180, 6]


def test_canonical_mf4_hex_ids_still_win_over_the_decimal_default() -> None:
    """Evidence beats the default: an 0x prefix or a hex letter is still hex."""
    raw = (
        b"timestamp,can_id,b0,b1,b2,b3,b4,b5,b6,b7\n"
        b"0.0,7EC,1,2,3,4,5,6,7,8\n"
        b"0.1,7E4,1,2,3,4,5,6,7,8\n"
    )
    assert parse_csv_frames(raw, "hexish.csv")["can_id"].tolist() == [0x7EC, 0x7E4]


def test_extra_columns_are_not_the_canonical_format() -> None:
    """timestamp,can_id,b0..b7,state,attack_type is a replay log and stays hex."""
    raw = (
        b"timestamp,can_id,b0,b1,b2,b3,b4,b5,b6,b7,state,attack_type\n"
        b"0.0,260,0,128,0,51,0,80,5,0,idle,none\n"
    )
    assert parse_csv_frames(raw, "replay.csv")["can_id"].tolist() == [0x260]


def test_real_converted_file_matches_the_replay_loader() -> None:
    """The two Python entry points must read one file identically."""
    converted = ROOT / "backend" / "ml" / "outputs" / "mf4_converted" / "00000158-64CBC290_0da3381ea433ee5a.csv"
    if not converted.exists():
        import pytest
        pytest.skip("converted MF4 not present")

    from backend.offline.session_analyzer import _load_csv

    df = parse_csv_frames(converted.read_bytes(), converted.name)
    loader_ids = [f[1] for f in _load_csv(converted)]

    assert df["can_id"].tolist() == loader_ids
    assert 0x7EC in loader_ids and 0x2028 not in loader_ids
