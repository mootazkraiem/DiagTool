"""
recordings.py
─────────────
The training corpus as a list of recordings, each read by a loader whose
timestamp unit is fixed by the file format - never guessed from the numbers.

    format         unit        source of the unit
    ─────────────  ──────────  ──────────────────────────────────────────────
    mf4            seconds     ASAM MDF master channel (asammdf)
    hcrl_txt       seconds     "Timestamp: <epoch s>" lines (HCRL normal run)
    candump_ts     seconds     candump -t "(sec.usec) iface ID#DATA"
    vector_asc     seconds     Vector ASC trace; "base hex" required
    savvycan_csv   microsec.   SavvyCAN/GVRET CSV "Time Stamp" column
    busmon         seconds     wall-clock HH:MM:SS:mmm

Formats whose files do not state a unit (BusMaster/Parker TSV, PCAN plain
text) and captures without timestamps (candump without -t) are not loaded:
their timing cannot be established, and it is not repaired.

A loaded recording is then checked for physical plausibility in its declared
unit (``timestamp_problems``). Nothing is rescaled to make it pass.

Loaders keep the file's frame order and never sample rows. A frame cap, where
one applies, keeps a contiguous block from the start of the file.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

BYTE_COLS = [f"b{i}" for i in range(8)]
COLUMNS = ["timestamp", "can_id", *BYTE_COLS]

LOADABLE_FORMATS = ("mf4", "hcrl_txt", "candump_ts", "vector_asc", "savvycan_csv", "busmon")

# Rejection reasons for formats that are recognised but not loadable.
UNITLESS_FORMATS = {
    "parker_tsv": "BusMaster/Parker TSV 'Time' column does not state its unit",
    "pcan_text": "PCAN plain-text timestamp column does not state its unit",
    "candump": "candump without -t has no timestamps",
}

# Physical plausibility of a recording's timing, in its declared unit.
MAX_FRAMES_PER_SECOND = 10_000.0       # a 1 Mbit/s bus carries at most ~8,700 frames/s
MIN_FRAMES_PER_SECOND = 1.0
MAX_GAP_SECONDS = 3600.0
MAX_BACKWARD_FRACTION = 0.001          # out-of-order steps allowed (multi-channel merge)
MAX_BACKWARD_STEP_SECONDS = 1.0        # a larger jump back is a concatenation or clock reset
MIN_RECORDING_FRAMES = 1000


@dataclass
class Recording:
    vehicle: str
    path: Path
    fmt: str
    frame_cap: int | None = None        # contiguous prefix; None = whole file


# ── format detection ─────────────────────────────────────────────────────────

_CANDUMP_TS = re.compile(r"\(([0-9.]+)\)\s+\S+\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]*)")


def detect_format(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".mf4":
        return "mf4"
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            lines = [fh.readline() for _ in range(8)]
    except OSError:
        return "unreadable"
    first = lines[0].replace("\x00", "").lstrip("﻿")
    if first.startswith("Timestamp:"):
        return "hcrl_txt"
    if "Time Stamp" in first and "ID" in first and "D1" in first:
        return "savvycan_csv"
    if "ParserFlags" in first:
        return "parker_tsv"
    if first.strip().startswith("date ") or any("Begin Triggerblock" in ln for ln in lines):
        return "vector_asc"
    if "Direction" in first and "Frame ID" in first:
        return "busmon"
    if any(_CANDUMP_TS.match(ln.strip()) for ln in lines):
        return "candump_ts"
    for ln in lines:
        s = ln.strip()
        if s.startswith("can") and "[" in s:
            return "candump"
    for ln in lines:
        parts = ln.strip().split()
        if (len(parts) >= 3 and parts[0].isdigit()
                and all(c in "0123456789ABCDEFabcdef" for c in parts[1]) and parts[2].isdigit()):
            return "pcan_text"
    return "unknown"


# ── loaders (declared unit → seconds, file order, no sampling) ────────────────

def _frame(rows: list[list]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=COLUMNS)
    df["timestamp"] = df["timestamp"].astype(np.float64)
    df["can_id"] = df["can_id"].astype(np.int64)
    for c in BYTE_COLS:
        df[c] = df[c].astype(np.int64)
    return df


def _pad(bs: list[int]) -> list[int]:
    bs = [b & 0xFF for b in bs][:8]
    return bs + [0] * (8 - len(bs))


def _load_mf4(path: Path, cap: int | None) -> pd.DataFrame:
    from asammdf import MDF

    df = MDF(str(path)).to_dataframe()
    id_col = next((c for c in df.columns if c.endswith(".ID")), None)
    db_col = next((c for c in df.columns if c.endswith(".DataBytes")), None)
    if id_col is None or db_col is None:
        raise ValueError("MF4 has no CAN ID / DataBytes channels")
    if cap is not None:
        df = df.iloc[:cap]
    rows = [[float(ts), int(cid), *_pad(list(db))]
            for ts, cid, db in zip(df.index.to_numpy(dtype=np.float64), df[id_col].to_numpy(), df[db_col])]
    return _frame(rows)


_HCRL = re.compile(r"Timestamp:\s*([0-9]+\.[0-9]+)\s+ID:\s*([0-9A-Fa-f]+)\s+\S+\s+DLC:\s*(\d+)\s+(.+)")


def _load_hcrl_txt(path: Path, cap: int | None) -> pd.DataFrame:
    rows = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = _HCRL.match(line.strip())
            if not m:
                continue
            bs = [int(b, 16) for b in m.group(4).split()[: int(m.group(3))]]
            rows.append([float(m.group(1)), int(m.group(2), 16), *_pad(bs)])
            if cap is not None and len(rows) >= cap:
                break
    return _frame(rows)


def _load_candump_ts(path: Path, cap: int | None) -> pd.DataFrame:
    rows = []
    with open(path, encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            m = _CANDUMP_TS.match(line.strip())
            if not m:
                continue
            data = m.group(3)
            bs = [int(data[j:j + 2], 16) for j in range(0, len(data) - 1, 2)]
            rows.append([float(m.group(1)), int(m.group(2), 16), *_pad(bs)])
            if cap is not None and len(rows) >= cap:
                break
    return _frame(rows)


def _load_vector_asc(path: Path, cap: int | None) -> pd.DataFrame:
    rows = []
    with open(path, encoding="utf-8", errors="ignore") as fh:
        header = "".join(fh.readline() for _ in range(3))
        if "base hex" not in header:
            raise ValueError("ASC trace is not 'base hex'; identifier radix cannot be established")
        for line in fh:
            parts = line.strip().split()
            if len(parts) < 6 or "d" not in parts:
                continue
            try:
                ts = float(parts[0])
                cid = int(parts[2].rstrip("x"), 16)
                i = parts.index("d")
                dlc = int(parts[i + 1])
                bs = [int(b, 16) for b in parts[i + 2:i + 2 + dlc]]
            except (ValueError, IndexError):
                continue
            rows.append([ts, cid, *_pad(bs)])
            if cap is not None and len(rows) >= cap:
                break
    return _frame(rows)


def _load_savvycan_csv(path: Path, cap: int | None) -> pd.DataFrame:
    raw = pd.read_csv(path, dtype=str, index_col=False, nrows=cap, encoding_errors="replace")
    raw.columns = [c.strip().lstrip("﻿") for c in raw.columns]
    dcols = [f"D{i}" for i in range(1, 9)]
    if "Time Stamp" not in raw.columns or "ID" not in raw.columns or any(c not in raw.columns for c in dcols):
        raise ValueError("SavvyCAN CSV lacks Time Stamp / ID / D1..D8")
    ts = pd.to_numeric(raw["Time Stamp"].str.strip(), errors="coerce")
    if ts.isna().any():
        raise ValueError(f"{int(ts.isna().sum())} rows have a non-numeric Time Stamp")
    rows = []
    for t, cid, *ds in zip(ts.to_numpy(dtype=np.float64), raw["ID"], *(raw[c] for c in dcols)):
        bs = [int(str(d).strip(), 16) for d in ds if isinstance(d, str) and str(d).strip() not in ("", "nan")]
        rows.append([t / 1e6, int(str(cid).strip(), 16), *_pad(bs)])
    return _frame(rows)


def _load_busmon(path: Path, cap: int | None) -> pd.DataFrame:
    rows = []
    with open(path, encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            line = line.replace("\x00", "").strip()
            parts = line.split()
            if not line or line.startswith("NO") or len(parts) < 10:
                continue
            try:
                h, m, s, ms = parts[2].split(":")
                ts = int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0
                cid = int(parts[7], 16)
                dlc = int(parts[8])
                bs = [int(b, 16) for b in parts[9:9 + dlc]]
            except (ValueError, IndexError):
                continue
            rows.append([ts, cid, *_pad(bs)])
            if cap is not None and len(rows) >= cap:
                break
    return _frame(rows)


_LOADERS = {
    "mf4": _load_mf4,
    "hcrl_txt": _load_hcrl_txt,
    "candump_ts": _load_candump_ts,
    "vector_asc": _load_vector_asc,
    "savvycan_csv": _load_savvycan_csv,
    "busmon": _load_busmon,
}


def load_recording(rec: Recording) -> pd.DataFrame:
    """Frames in file order, timestamps in seconds in the format's declared unit."""
    if rec.fmt not in _LOADERS:
        raise ValueError(f"format '{rec.fmt}' is not loadable")
    return _LOADERS[rec.fmt](rec.path, rec.frame_cap)


# ── validation ───────────────────────────────────────────────────────────────

def timestamp_problems(frames: pd.DataFrame) -> list[str]:
    """Reasons this recording's timing cannot be trusted; empty when it can."""
    n = len(frames)
    if n < MIN_RECORDING_FRAMES:
        return [f"only {n} frames (minimum {MIN_RECORDING_FRAMES})"]
    ts = frames["timestamp"].to_numpy(dtype=np.float64)
    if not np.isfinite(ts).all():
        return ["non-finite timestamps"]
    if (ts < 0).any():
        return ["negative timestamps"]
    problems = []
    steps = np.diff(ts)
    backward = int((steps < 0).sum())
    if backward > MAX_BACKWARD_FRACTION * len(steps):
        problems.append(f"{backward} of {len(steps)} steps go backwards in time")
    elif backward and float(-steps.min()) > MAX_BACKWARD_STEP_SECONDS:
        problems.append(f"time jumps backwards by {float(-steps.min()):,.1f} s")
    duration = float(ts.max() - ts.min())
    if duration <= 0:
        return problems + ["zero duration: all timestamps equal"]
    rate = (n - 1) / duration
    if rate > MAX_FRAMES_PER_SECOND:
        problems.append(f"{rate:,.0f} frames/s exceeds the physical bus limit ({MAX_FRAMES_PER_SECOND:,.0f})")
    if rate < MIN_FRAMES_PER_SECOND:
        problems.append(f"{rate:.3g} frames/s over {duration:,.0f} s is implausibly sparse")
    max_gap = float(np.max(np.abs(steps))) if len(steps) else 0.0
    if max_gap > MAX_GAP_SECONDS:
        problems.append(f"a {max_gap:,.0f} s gap between consecutive frames")
    return problems


def chronological(frames: pd.DataFrame) -> pd.DataFrame:
    """Stable sort by timestamp (only reorders the few out-of-order steps validation allows)."""
    return frames.sort_values("timestamp", kind="mergesort").reset_index(drop=True)


def content_hash(frames: pd.DataFrame) -> str:
    """Identity of a capture's traffic: its (can_id, payload) sequence in time order.

    Independent of the file format and of the timestamp origin, so the same
    capture exported twice hashes the same.
    """
    ordered = chronological(frames)[["can_id", *BYTE_COLS]].to_numpy(dtype=np.int64)
    return hashlib.sha256(np.ascontiguousarray(ordered).tobytes()).hexdigest()


def traffic_rows(frames: pd.DataFrame) -> np.ndarray:
    """(can_id, b0..b7) per frame in time order - what content_hash and contains() compare."""
    return np.ascontiguousarray(chronological(frames)[["can_id", *BYTE_COLS]].to_numpy(dtype=np.int64))


def contains(big: np.ndarray, small: np.ndarray) -> bool:
    """True when ``small`` appears as a contiguous run of frames inside ``big``.

    Catches an evaluation file exported as a slice of a training recording
    (e.g. its first 50,000 frames), which an identity hash cannot see.
    """
    n, m = len(big), len(small)
    if m == 0 or m > n:
        return False
    starts = np.flatnonzero((big[: n - m + 1] == small[0]).all(axis=1))
    return any(np.array_equal(big[i:i + m], small) for i in starts)


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
