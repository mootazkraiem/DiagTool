"""Regression tests for the replay/offline CSV loader (session_analyzer._load_csv).

This is the loader behind _load_file, which the replay runner and the offline
session analyzer both use. It recognised a header only when it contained a
column named exactly "can_id", or both "id" and "d1". An asammdf MF4 export
names them CAN_DataFrame.CAN_DataFrame.ID and .DataBytes, so a real Skoda
recording produced zero frames with no error and the replay scored an empty
stream while reporting success.

Expected values are read from the raw file here, so the loader is checked
against the source data rather than against its own output.
"""
from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.offline.session_analyzer import _load_csv, _load_file  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SKODA = ROOT / "assets" / "Skoda Enyaq" / "file_16.csv"

# Read independently from the raw .ID column of the recording.
SKODA_ID_COUNTS = {
    402522235: 4178, 402391163: 3798, 2001: 3779, 1862: 1516, 1968: 1516,
    1895: 1516, 402391225: 760, 402522297: 760, 402391158: 758, 402522230: 758,
}

CANONICAL = (
    "timestamp,can_id,b0,b1,b2,b3,b4,b5,b6,b7\n"
    "0.0,2028,16,62,98,1,1,239,251,231\n"
    "0.25,2020,3,34,1,1,170,170,170,170\n"
    "0.50,25,15,36,176,201,0,238,79,127\n"
)

SAVVYCAN = (
    "Time Stamp,ID,Extended,Dir,Bus,LEN,D1,D2,D3,D4,D5,D6,D7,D8\n"
    "1000,7E8,false,Rx,0,8,03,41,0C,1A,F8,00,00,00\n"
    "2000,1A2,false,Rx,0,8,DE,AD,BE,EF,01,02,03,04\n"
)


# ── the regression: real asammdf MF4 export ──────────────────────────────────

@pytest.mark.skipif(not SKODA.exists(), reason="Skoda recording not present")
def test_asammdf_export_is_parsed_not_silently_empty() -> None:
    frames = list(_load_csv(SKODA))

    with SKODA.open(newline="", encoding="utf-8") as fh:
        expected_rows = sum(1 for _ in csv.reader(fh)) - 1

    assert len(frames) == expected_rows == 19339, "every row of the recording must be read"
    assert dict(Counter(f[1] for f in frames)) == SKODA_ID_COUNTS


@pytest.mark.skipif(not SKODA.exists(), reason="Skoda recording not present")
def test_asammdf_export_reads_id_column_not_bus_channel() -> None:
    frames = list(_load_csv(SKODA))
    # BusChannel is 1 on every row of this export and sits before the identifier.
    assert all(f[1] != 1 for f in frames)
    assert len({f[1] for f in frames}) == 10


@pytest.mark.skipif(not SKODA.exists(), reason="Skoda recording not present")
def test_asammdf_export_payload_and_timestamps_are_real() -> None:
    frames = list(_load_csv(SKODA))

    assert frames[0][0] == 0.0
    assert frames[0][1] == 0x17FC00B9
    assert frames[0][2] == (3, 34, 70, 91, 85, 85, 85, 85)

    timestamps = [f[0] for f in frames]
    assert timestamps == sorted(timestamps), "capture order must be preserved"
    assert timestamps[-1] == pytest.approx(1896.5153, abs=1e-3)
    assert all(len(f[2]) == 8 and all(0 <= b <= 255 for b in f[2]) for f in frames)


# ── formats that already worked keep their exact semantics ───────────────────

def test_canonical_csv_reads_identifiers_as_decimal(tmp_path: Path) -> None:
    """2028 is decimal here (UDS response 0x7EC), not hex 0x2028.

    This is the form the MF4 converter writes and the form every measurement on
    the Kia recording was taken from.
    """
    path = tmp_path / "canonical.csv"
    path.write_text(CANONICAL, encoding="utf-8")

    frames = list(_load_csv(path))

    assert [f[1] for f in frames] == [0x7EC, 0x7E4, 0x19]
    assert frames[0][2] == (16, 62, 98, 1, 1, 239, 251, 231)
    assert frames[2][0] == 0.50


def test_savvycan_csv_reads_identifiers_as_hex(tmp_path: Path) -> None:
    path = tmp_path / "savvy.csv"
    path.write_text(SAVVYCAN, encoding="utf-8")

    frames = list(_load_csv(path))

    assert [f[1] for f in frames] == [0x7E8, 0x1A2]
    assert frames[1][2] == (0xDE, 0xAD, 0xBE, 0xEF, 1, 2, 3, 4)
    # SavvyCAN "Time Stamp" is microseconds (the format's unit, and the training
    # loader's); the previous /1000 read it as milliseconds.
    assert [f[0] for f in frames] == [1000 / 1e6, 2000 / 1e6]


# ── an unreadable file must say so ───────────────────────────────────────────

def test_unparseable_csv_raises_instead_of_yielding_nothing(tmp_path: Path) -> None:
    path = tmp_path / "not_can.csv"
    path.write_text("alpha,beta,gamma\n1,2,3\n4,5,6\n", encoding="utf-8")

    with pytest.raises(ValueError) as excinfo:
        list(_load_csv(path))

    message = str(excinfo.value)
    assert "not_can.csv" in message, "the error names the file"
    assert "alpha,beta,gamma" in message, "the error shows the header it found"


def test_empty_csv_raises(tmp_path: Path) -> None:
    path = tmp_path / "empty.csv"
    path.write_text("", encoding="utf-8")

    with pytest.raises(Exception):
        list(_load_csv(path))


def test_unsupported_extension_raises(tmp_path: Path) -> None:
    path = tmp_path / "capture.bin"
    path.write_bytes(b"\x00\x01\x02")

    with pytest.raises(ValueError, match="Unsupported file format"):
        list(_load_file(path))



# ── SavvyCAN replay (Step 12, P0-2) ──────────────────────────────────────────

JAGUAR = ROOT / "assets" / "EV-CANlogs-main" / "Jaguar IPACE"


def test_savvycan_rows_with_trailing_comma_are_not_dropped(tmp_path: Path) -> None:
    """Every SavvyCAN row ends with "," - pandas shifted the columns and every row was lost."""
    path = tmp_path / "trailing.csv"
    path.write_text("Time Stamp,ID,Extended,Dir,Bus,LEN,D1,D2,D3,D4,D5,D6,D7,D8\n"
                    "12720014,0000014C,false,Rx,0,8,00,00,10,68,0F,1A,0F,25,\n"
                    "12720634,000000A3,false,Rx,0,8,B2,06,00,00,00,00,00,00,\n", encoding="utf-8")
    frames = list(_load_file(path))
    assert [(f[0], f[1]) for f in frames] == [(12.720014, 0x14C), (12.720634, 0xA3)]
    assert frames[0][2] == (0x00, 0x00, 0x10, 0x68, 0x0F, 0x1A, 0x0F, 0x25)


@pytest.mark.skipif(not JAGUAR.is_dir(), reason="Jaguar recordings not present")
def test_jaguar_savvycan_replay_matches_training_loader() -> None:
    import numpy as np

    from backend.ml.training import recordings as rec

    for path in sorted(JAGUAR.glob("*.csv")):
        frames = list(_load_file(path))
        trained = rec.load_recording(rec.Recording("jaguar_ipace", path, "savvycan_csv"))
        assert len(frames) == len(trained) > 0, path.name
        assert np.array_equal(np.array([f[0] for f in frames]), trained["timestamp"].to_numpy())
        assert np.array_equal(np.array([f[1] for f in frames]), trained["can_id"].to_numpy())
        assert np.array_equal(np.array([f[2] for f in frames]),
                              trained[[f"b{i}" for i in range(8)]].to_numpy())


def test_zero_frame_savvycan_raises(tmp_path: Path) -> None:
    path = tmp_path / "nothing.csv"
    path.write_text("Time Stamp,ID,Extended,Dir,Bus,LEN,D1,D2\nnot,a,frame,,,,,\n", encoding="utf-8")
    with pytest.raises(ValueError, match="No CAN frames could be parsed from 'nothing.csv'"):
        list(_load_file(path))
