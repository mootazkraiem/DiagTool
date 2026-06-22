from __future__ import annotations

import json
import re
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from sklearn.decomposition import PCA
from sklearn.cluster import KMeans
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import RobustScaler
from sklearn.feature_selection import VarianceThreshold

try:
    from backend.ml.feature_engineering import load_kaggle_dataset, preprocess_pipeline
    from backend.progress import print_progress
except ModuleNotFoundError:
    import sys
    sys.path.append(str(Path(__file__).resolve().parents[2]))
    from backend.ml.feature_engineering import load_kaggle_dataset, preprocess_pipeline
    from backend.progress import print_progress

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ASSETS_ROOT = PROJECT_ROOT / "assets"
TRAIN_FEATURE_ROOT = ASSETS_ROOT / "processed_features" / "train"
MODEL_ROOT = ASSETS_ROOT / "models"
SCORE_DIST_ROOT = MODEL_ROOT / "score_distributions"
PCA_OUT_ROOT = PROJECT_ROOT / "outputs" / "pca"
KAGGLE_NORMAL_PATH = PROJECT_ROOT / "assets" / "archive" / "normal_run_data.txt"
EV_LOGS_ROOT = ASSETS_ROOT / "EV-CANlogs-main"
SKODA_ROOT = ASSETS_ROOT / "Skoda Enyaq"
MF4_TRAIN_ROOT = ASSETS_ROOT / "Train"
ROAD_ROOT = ASSETS_ROOT / "road" / "road"
CAR_HACKING_ROOT = ASSETS_ROOT / "9) Car-Hacking Dataset"
STATE_NAMES = ["parking", "idle", "driving"]
MIN_ROWS_PER_STATE = 2000  # lowered from 5000 to allow smaller per-vehicle datasets
ROBUST_K = 3.0
CONTAMINATION = 0.02
REQUIRED_FEATURES = [
    "time_diff",
    "rolling_std_time_diff",
    "rolling_mean_byte_diff",
    "rolling_byte_diff_std",
    "rolling_max_byte_diff",
    "rolling_min_byte_diff",
    "rolling_range_byte_diff",
    "msg_frequency",
    "byte_diff",
    "changed_bytes_count",
]
STATE_FEATS = REQUIRED_FEATURES.copy()
FEATURES = REQUIRED_FEATURES.copy()



def _normalize_ts(ts: pd.Series) -> pd.Series:
    """Convert hardware timestamps to seconds, normalized to start at 0.

    Handles: nanoseconds, microseconds, milliseconds, seconds, negative timestamps,
    and overflow values (e.g. Nissan 62kWh logs with ~1.8e19 µs timestamps).
    """
    # Drop overflow and negative values before any scaling
    ts = ts.clip(lower=0)
    ts = ts[ts < 2e18]  # anything beyond ~6B years in ns is corrupt
    if len(ts) == 0:
        return ts
    med = float(ts.median())
    if med > 1e15:
        ts = ts / 1e9   # nanoseconds → seconds
    elif med > 1e12:
        ts = ts / 1e6   # microseconds → seconds
    elif med > 1e9:
        ts = ts / 1e3   # milliseconds → seconds
    ts = ts - ts.min()
    return ts


def load_ev_can_log(path: Path) -> pd.DataFrame | None:
    """Parse SavvyCAN-style EV CSV: Time Stamp,ID,...,D1..D8

    Handles trailing commas (Jaguar I-PACE, Kia Soul), negative timestamps
    (Kia eNiro), and overflow timestamps (Nissan 62kWh).
    """
    try:
        # index_col=False prevents pandas from treating the extra field created
        # by a trailing comma as a row index, which would shift all columns.
        raw = pd.read_csv(path, dtype=str, on_bad_lines="skip", index_col=False)
        raw.columns = [c.strip() for c in raw.columns]
        if "Time Stamp" not in raw.columns or "ID" not in raw.columns:
            return None
        byte_dcols = [f"D{i}" for i in range(1, 9) if f"D{i}" in raw.columns]
        if len(byte_dcols) < 8:
            return None
        # Use uint=False so negative values are preserved as floats, not NaN
        ts = pd.to_numeric(raw["Time Stamp"].str.strip(), errors="coerce")
        valid = ts.notna()
        ts = ts[valid]
        if len(ts) < 50:
            return None
        ts = _normalize_ts(ts)
        if len(ts) < 50:
            return None
        sub = raw[valid].reset_index(drop=True)
        # Re-align after _normalize_ts may have dropped overflow rows
        sub = sub.iloc[:len(ts)].reset_index(drop=True)
        out = pd.DataFrame()
        out["timestamp"] = ts.values
        def _hex_id(x: str) -> str | float:
            try:
                return str(int(str(x).strip(), 16))
            except Exception:
                return float("nan")
        out["can_id"] = sub["ID"].str.strip().apply(_hex_id)
        for i, dcol in enumerate(byte_dcols[:8]):
            col_idx = i  # capture for closure
            out[f"b{col_idx}"] = sub[dcol].apply(
                lambda x: int(str(x).strip(), 16) if str(x).strip() not in ("", "nan") else 0
            )
        out = out.dropna(subset=["can_id"]).reset_index(drop=True)
        out["can_id"] = out["can_id"].astype(str)
        return out if len(out) >= 50 else None
    except Exception as exc:
        print(f"[WARN] load_ev_can_log failed for {path.name}: {exc}")
        return None


def load_skoda_log(path: Path) -> pd.DataFrame | None:
    """Parse Skoda/MF4-derived CSV: timestamps, ID (decimal), DataBytes as [b0 b1 ...]"""
    try:
        raw = pd.read_csv(path, dtype=str, on_bad_lines="skip")
        raw.columns = [c.strip() for c in raw.columns]
        ts_col = next((c for c in raw.columns if c.lower().startswith("timestamp")), None)
        id_col = next(
            (c for c in raw.columns if re.search(r"\bID\b", c, re.IGNORECASE)), None
        )
        db_col = next(
            (c for c in raw.columns if "DataBytes" in c or "data_bytes" in c.lower()), None
        )
        if not (ts_col and id_col and db_col):
            return None
        ts = pd.to_numeric(raw[ts_col].str.strip(), errors="coerce")
        valid = ts.notna()
        ts = ts[valid]
        if len(ts) < 50:
            return None
        ts = _normalize_ts(ts)
        sub = raw[valid].reset_index(drop=True)
        out = pd.DataFrame()
        out["timestamp"] = ts.values
        can_ids = pd.to_numeric(sub[id_col].str.strip(), errors="coerce")
        out["can_id"] = can_ids.apply(lambda x: str(int(x)) if pd.notna(x) else float("nan"))
        def _parse_databytes(cell: str) -> list[int]:
            nums = re.findall(r"\d+", str(cell))
            ints = [int(n) & 0xFF for n in nums]
            while len(ints) < 8:
                ints.append(0)
            return ints[:8]
        parsed_bytes = sub[db_col].apply(_parse_databytes)
        for i in range(8):
            out[f"b{i}"] = parsed_bytes.apply(lambda lst, _i=i: lst[_i])
        out = out.dropna(subset=["can_id"]).reset_index(drop=True)
        out["can_id"] = out["can_id"].astype(str)
        return out if len(out) >= 50 else None
    except Exception as exc:
        print(f"[WARN] load_skoda_log failed for {path.name}: {exc}")
        return None


def load_mf4_log(path: Path) -> pd.DataFrame | None:
    """Load a CSS Electronics CANedge MF4 file into the standard training frame format.

    Channel names follow the asammdf CAN_DataFrame convention:
      CAN_DataFrame.CAN_DataFrame.ID         — integer CAN ID (11-bit or 29-bit)
      CAN_DataFrame.CAN_DataFrame.DataBytes  — numpy uint8 array per row
    Index is the timestamp in seconds (float64).
    """
    try:
        from asammdf import MDF
    except ImportError:
        print("[WARN] asammdf not installed — skipping MF4:", path.name)
        return None
    try:
        mdf = MDF(str(path))
        df = mdf.to_dataframe()
    except Exception as exc:
        print(f"[WARN] MF4 read failed for {path.name}: {exc}")
        return None

    # Locate ID and DataBytes columns (names vary slightly across firmware versions)
    id_col = next((c for c in df.columns if c.endswith(".ID")), None)
    db_col = next((c for c in df.columns if c.endswith(".DataBytes")), None)
    if id_col is None or db_col is None:
        print(f"[WARN] MF4 missing ID or DataBytes channel: {path.name}")
        return None

    ts = df.index.to_series().astype(float)
    if len(ts) < 50:
        return None
    ts = _normalize_ts(ts)

    out = pd.DataFrame()
    out["timestamp"] = ts.values

    # CAN IDs: 29-bit extended IDs (> 0x7FF) are UDS diagnostic frames from CANedge pollers.
    # We keep them — they contribute valid timing/payload statistics for normal baseline.
    raw_ids = df[id_col].to_numpy(dtype=np.int64)
    out["can_id"] = [str(int(i)) for i in raw_ids]

    def _parse_db(val) -> list[int]:
        try:
            arr = list(val)
            bs = [int(b) & 0xFF for b in arr]
        except Exception:
            bs = []
        while len(bs) < 8:
            bs.append(0)
        return bs[:8]

    parsed_bytes = [_parse_db(v) for v in df[db_col]]
    for i in range(8):
        out[f"b{i}"] = [row[i] for row in parsed_bytes]

    out = out.dropna(subset=["can_id"]).reset_index(drop=True)
    return out if len(out) >= 50 else None


def load_all_mf4_logs() -> list[tuple[str, pd.DataFrame]]:
    """Load all MF4 files from assets/Train/ — the real EV UDS logs."""
    sources: list[tuple[str, pd.DataFrame]] = []
    if not MF4_TRAIN_ROOT.exists():
        print(f"[WARN] MF4 train root not found: {MF4_TRAIN_ROOT}")
        return sources

    for mf4_path in sorted(MF4_TRAIN_ROOT.rglob("*.MF4")):
        # Vehicle name = top-level folder under Train/ (e.g. "Nissan Leaf 2019")
        try:
            rel = mf4_path.relative_to(MF4_TRAIN_ROOT)
            vname = rel.parts[0].strip().lower().replace(" ", "_")
        except Exception:
            vname = mf4_path.stem[:20].lower().replace(" ", "_")

        df = load_mf4_log(mf4_path)
        if df is None:
            print(f"  [SKIP MF4] {mf4_path.name}")
            continue
        print(f"  [MF4] {vname}/{mf4_path.name}: {len(df):,} frames")
        sources.append((vname, df))

    return sources


def _smart_load_csv(path: Path) -> pd.DataFrame | None:
    """Try all known EV log formats; return parsed DataFrame or None."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            header = fh.readline()
    except Exception:
        return None
    if "Time Stamp" in header and "D1" in header:
        return load_ev_can_log(path)
    if "DataBytes" in header or "timestamps" in header.lower():
        return load_skoda_log(path)
    result = load_ev_can_log(path)
    if result is not None:
        return result
    return load_skoda_log(path)


# ── Non-CSV format parsers ────────────────────────────────────────────────────

def load_parker_tsv(path: Path) -> pd.DataFrame | None:
    """BusMaster/Parker TSV: ParserFlags\\tCh\\t...\\tTime\\t...\\tCAN ID\\tLen\\tData"""
    try:
        raw = pd.read_csv(path, sep="\t", dtype=str, on_bad_lines="skip")
        raw.columns = [c.strip() for c in raw.columns]
        time_col = next((c for c in raw.columns if c.strip() == "Time"), None)
        id_col = next((c for c in raw.columns if "CAN ID" in c), None)
        data_col = next((c for c in raw.columns if c.strip() == "Data"), None)
        if not all([time_col, id_col, data_col]):
            return None
        ts = pd.to_numeric(raw[time_col].str.strip(), errors="coerce")
        valid = ts.notna()
        ts = ts[valid]
        if len(ts) < 50:
            return None
        ts = _normalize_ts(ts)
        if len(ts) < 50:
            return None
        sub = raw[valid].reset_index(drop=True).iloc[:len(ts)].reset_index(drop=True)
        out = pd.DataFrame()
        out["timestamp"] = ts.values

        def _parse_can_id(x: str) -> object:
            s = str(x).strip()
            try:
                return str(int(s, 16) if s.lower().startswith("0x") else int(s))
            except Exception:
                return float("nan")

        out["can_id"] = sub[id_col].apply(_parse_can_id)

        def _parse_data(x: str) -> list:
            bs = []
            for p in str(x).strip().split():
                try:
                    bs.append(int(p, 16) & 0xFF)
                except Exception:
                    pass
            while len(bs) < 8:
                bs.append(0)
            return bs[:8]

        parsed = sub[data_col].apply(_parse_data)
        for i in range(8):
            out[f"b{i}"] = parsed.apply(lambda lst, _i=i: lst[_i])
        out = out.dropna(subset=["can_id"]).reset_index(drop=True)
        out["can_id"] = out["can_id"].astype(str)
        return out if len(out) >= 50 else None
    except Exception as exc:
        print(f"[WARN] load_parker_tsv failed for {path.name}: {exc}")
        return None


def load_asc_log(path: Path) -> pd.DataFrame | None:
    """Vector ASC: 'timestamp channel CAN_ID Rx d DLC B0 B1...'"""
    rows: list[list] = []
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            for raw_line in fh:
                parts = raw_line.strip().split()
                if len(parts) < 8:
                    continue
                try:
                    ts = float(parts[0])
                except ValueError:
                    continue
                can_id_str = parts[2]
                try:
                    can_id = str(int(can_id_str, 16))
                except Exception:
                    continue
                try:
                    d_idx = parts.index("d")
                    dlc = int(parts[d_idx + 1])
                    byte_parts = parts[d_idx + 2: d_idx + 2 + dlc]
                except (ValueError, IndexError):
                    continue
                bs = []
                for bp in byte_parts:
                    try:
                        bs.append(int(bp, 16) & 0xFF)
                    except Exception:
                        bs.append(0)
                while len(bs) < 8:
                    bs.append(0)
                rows.append([ts, can_id] + bs[:8])
    except Exception as exc:
        print(f"[WARN] load_asc_log failed for {path.name}: {exc}")
        return None
    if len(rows) < 20:
        return None
    df = pd.DataFrame(rows, columns=["timestamp", "can_id"] + [f"b{i}" for i in range(8)])
    ts = _normalize_ts(df["timestamp"])
    if len(ts) < 20:
        return None
    df = df.iloc[:len(ts)].copy()
    df["timestamp"] = ts.values
    return df


def load_pcan_text(path: Path) -> pd.DataFrame | None:
    """PCAN plain text (no header): 'timestamp_ms  HEX_ID  DLC  B0 B1 ...'"""
    rows: list[list] = []
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            for raw_line in fh:
                line = raw_line.strip()
                if not line:
                    continue
                parts = line.split()
                if len(parts) < 3:
                    continue
                try:
                    ts = float(parts[0])
                    can_id = str(int(parts[1], 16))
                    dlc = int(parts[2])
                except (ValueError, IndexError):
                    continue
                bs = []
                for bp in parts[3: 3 + dlc]:
                    try:
                        bs.append(int(bp, 16) & 0xFF)
                    except Exception:
                        bs.append(0)
                while len(bs) < 8:
                    bs.append(0)
                rows.append([ts, can_id] + bs[:8])
    except Exception as exc:
        print(f"[WARN] load_pcan_text failed for {path.name}: {exc}")
        return None
    if len(rows) < 20:
        return None
    df = pd.DataFrame(rows, columns=["timestamp", "can_id"] + [f"b{i}" for i in range(8)])
    ts = _normalize_ts(df["timestamp"])
    if len(ts) < 20:
        return None
    df = df.iloc[:len(ts)].copy()
    df["timestamp"] = ts.values
    return df


def load_candump(path: Path) -> pd.DataFrame | None:
    """candump (no timestamp): '  can0  ID  [DLC]  B0 B1 ...'"""
    rows: list[list] = []
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            for idx, raw_line in enumerate(fh):
                line = raw_line.strip()
                if not line or not line.startswith("can"):
                    continue
                parts = line.split()
                if len(parts) < 3:
                    continue
                try:
                    can_id = str(int(parts[1], 16))
                    dlc = int(parts[2].strip("[]"))
                except (ValueError, IndexError):
                    continue
                bs = []
                for bp in parts[3: 3 + dlc]:
                    try:
                        bs.append(int(bp, 16) & 0xFF)
                    except Exception:
                        bs.append(0)
                while len(bs) < 8:
                    bs.append(0)
                rows.append([idx * 0.001, can_id] + bs[:8])
    except Exception as exc:
        print(f"[WARN] load_candump failed for {path.name}: {exc}")
        return None
    if len(rows) < 20:
        return None
    return pd.DataFrame(rows, columns=["timestamp", "can_id"] + [f"b{i}" for i in range(8)])


def load_busmon(path: Path) -> pd.DataFrame | None:
    """Nissan BusMon: 'NO  Direction  HH:MM:SS:mmm  Data frame  Standard frame  CAN_ID  DLC  bytes'"""
    rows: list[list] = []
    t0: float | None = None
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            for raw_line in fh:
                # BusMon files are often saved as UTF-16LE; when read as UTF-8 null
                # bytes appear inside every token.  Strip them before parsing.
                line = raw_line.replace("\x00", "").strip()
                if not line or line.startswith("NO"):
                    continue
                parts = line.split()
                # expected layout: NO  Dir  HH:MM:SS:mmm  Data  frame  Standard  frame  CAN_ID  DLC  b0..
                if len(parts) < 10:
                    continue
                try:
                    h, m, s, ms = parts[2].split(":")
                    ts = int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000
                    can_id = str(int(parts[7], 16))
                    dlc = int(parts[8])
                except (ValueError, IndexError):
                    continue
                if t0 is None:
                    t0 = ts
                bs = []
                for bp in parts[9: 9 + dlc]:
                    try:
                        bs.append(int(bp, 16) & 0xFF)
                    except Exception:
                        bs.append(0)
                while len(bs) < 8:
                    bs.append(0)
                rows.append([ts - t0, can_id] + bs[:8])
    except Exception as exc:
        print(f"[WARN] load_busmon failed for {path.name}: {exc}")
        return None
    if len(rows) < 20:
        return None
    return pd.DataFrame(rows, columns=["timestamp", "can_id"] + [f"b{i}" for i in range(8)])


def load_candump_ts(path: Path) -> pd.DataFrame | None:
    """Timestamped candump: '(ts) can0 ID#hexdata'"""
    rows: list[list] = []
    pattern = re.compile(r'\(([0-9.]+)\)\s+\S+\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]*)')
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            for raw_line in fh:
                m = pattern.match(raw_line.strip())
                if not m:
                    continue
                try:
                    ts = float(m.group(1))
                    can_id = str(int(m.group(2), 16))
                    hex_data = m.group(3)
                except Exception:
                    continue
                bs = [int(hex_data[j:j+2], 16) & 0xFF for j in range(0, len(hex_data) - 1, 2)]
                while len(bs) < 8:
                    bs.append(0)
                rows.append([ts, can_id] + bs[:8])
    except Exception as exc:
        print(f"[WARN] load_candump_ts failed for {path.name}: {exc}")
        return None
    if len(rows) < 20:
        return None
    df = pd.DataFrame(rows, columns=["timestamp", "can_id"] + [f"b{i}" for i in range(8)])
    ts = _normalize_ts(df["timestamp"])
    if len(ts) < 20:
        return None
    df = df.iloc[:len(ts)].copy()
    df["timestamp"] = ts.values
    return df


def _detect_text_format(path: Path) -> str:
    """Return format tag for non-CSV CAN log file, or 'unknown' to skip."""
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            lines = [fh.readline() for _ in range(6)]
    except Exception:
        return "unknown"
    first = lines[0]
    # Parker/BusMaster TSV
    if "ParserFlags" in first:
        return "parker_tsv"
    # Vector ASC
    if first.strip().startswith("date ") or "base hex" in first or "Begin Triggerblock" in first:
        return "asc"
    # PCAN trace / BMW PEAK PCAN viewer / PuTTY — skip
    if ";$FILEVERSION" in first or "CAN speed" in first or "=~=~=~=" in first:
        return "skip"
    # BMW PEAK viewer (lines start with ">")
    if any(ln.strip().startswith(">") for ln in lines):
        return "skip"
    # VW OVMS / OBD response: "7e0[7e8]:xxxx ..." — not raw CAN, skip
    if any(re.match(r'[0-9A-Fa-f]+\[[0-9A-Fa-f]+\]:', ln.strip()) for ln in lines):
        return "skip"
    # Nissan BusMon: header "NO    Direction  Time Scale  ... Frame ID  Length  Data"
    if "Direction" in first and "Frame ID" in first:
        return "busmon"
    # Timestamped candump: "(ts) can0 ID#bytes"
    for ln in lines:
        if re.match(r'\([0-9.]+\)\s+\S+\s+[0-9A-Fa-f]+#', ln.strip()):
            return "candump_ts"
    # candump without timestamp: "can0  ID  [DLC]  bytes"
    for ln in lines:
        stripped = ln.strip()
        if stripped.startswith("can") and "[" in stripped:
            return "candump"
    # PCAN plain text: digits  HEX_ID  DLC  bytes (no header row)
    for ln in lines:
        parts = ln.strip().split()
        if (len(parts) >= 3 and parts[0].isdigit()
                and all(c in "0123456789ABCDEFabcdef" for c in parts[1])
                and parts[2].isdigit()):
            return "pcan_text"
    return "unknown"


def _smart_load_text(path: Path) -> pd.DataFrame | None:
    """Detect format and parse any non-CSV CAN log file."""
    fmt = _detect_text_format(path)
    if fmt == "parker_tsv":
        return load_parker_tsv(path)
    if fmt == "asc":
        return load_asc_log(path)
    if fmt == "pcan_text":
        return load_pcan_text(path)
    if fmt == "candump":
        return load_candump(path)
    if fmt == "candump_ts":
        return load_candump_ts(path)
    if fmt == "busmon":
        return load_busmon(path)
    return None  # "skip" or "unknown"


def load_car_hacking_csv(path: Path) -> pd.DataFrame | None:
    """Car-Hacking Dataset CSV: timestamp,can_id_hex,dlc,b0..b7,flag  (R=normal, T=attack).
    Loads normal-traffic rows only (flag == 'R') for use as additional baseline training data.
    """
    try:
        df = pd.read_csv(
            path,
            header=None,
            names=["timestamp", "can_id", "dlc", "b0", "b1", "b2", "b3", "b4", "b5", "b6", "b7", "flag"],
            dtype=str,
            on_bad_lines="skip",
        )
        # Keep only normal-traffic rows
        df = df[df["flag"].str.strip() == "R"].copy()
        if len(df) < 20:
            return None
        df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce")
        df["can_id"] = df["can_id"].apply(lambda x: str(int(x, 16)) if pd.notna(x) else None)
        for col in [f"b{i}" for i in range(8)]:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
        df = df.dropna(subset=["timestamp", "can_id"])
        ts = _normalize_ts(df["timestamp"])
        if len(ts) < 20:
            return None
        df = df.iloc[:len(ts)].copy()
        df["timestamp"] = ts.values
        return df[["timestamp", "can_id"] + [f"b{i}" for i in range(8)]]
    except Exception as exc:
        print(f"[WARN] load_car_hacking_csv failed for {path.name}: {exc}")
        return None


def load_all_ev_logs() -> list[tuple[str, pd.DataFrame]]:
    """Load every EV CAN log from the assets directory trees.

    Loads CSV files (SavvyCAN) and all recognised text log formats
    (.log Parker TSV, .asc Vector ASC, .txt PCAN/candump).
    Skoda Enyaq CSVs are excluded — authoritative data comes from MF4.
    """
    sources: list[tuple[str, pd.DataFrame]] = []
    if not EV_LOGS_ROOT.exists():
        print(f"[WARN] EV logs dir not found: {EV_LOGS_ROOT}")
        return sources

    def _vname(p: Path) -> str:
        try:
            return p.relative_to(EV_LOGS_ROOT).parts[0].strip().lower().replace(" ", "_")
        except Exception:
            return p.stem.lower()[:30].replace(" ", "_")

    # CSV files (SavvyCAN / Skoda-derived)
    for csv_path in sorted(EV_LOGS_ROOT.rglob("*.csv")):
        df = _smart_load_csv(csv_path)
        if df is None:
            print(f"  [SKIP] {csv_path.name}")
            continue
        vname = _vname(csv_path)
        print(f"  [EV] {vname}/{csv_path.name}: {len(df):,} frames")
        sources.append((vname, df))

    # Text-format logs (.log, .asc, .txt)
    seen: set[Path] = set()
    for ext in ("*.log", "*.asc", "*.txt"):
        for text_path in sorted(EV_LOGS_ROOT.rglob(ext)):
            if text_path in seen:
                continue
            seen.add(text_path)
            df = _smart_load_text(text_path)
            if df is None:
                print(f"  [SKIP] {text_path.name}")
                continue
            vname = _vname(text_path)
            print(f"  [EV] {vname}/{text_path.name}: {len(df):,} frames")
            sources.append((vname, df))

    # ROAD dataset — ambient (normal) logs only; attacks excluded from training.
    # Files are large (1-3M frames each); sample to ROAD_FRAMES_PER_FILE for balance.
    ROAD_FRAMES_PER_FILE = 150_000
    if ROAD_ROOT.exists():
        ambient_dir = ROAD_ROOT / "ambient"
        road_logs = sorted(ambient_dir.glob("*.log")) if ambient_dir.exists() else []
        for log_path in road_logs:
            df = load_candump_ts(log_path)
            if df is None:
                print(f"  [SKIP] road/{log_path.name}")
                continue
            if len(df) > ROAD_FRAMES_PER_FILE:
                df = df.sample(n=ROAD_FRAMES_PER_FILE, random_state=42).reset_index(drop=True)
            print(f"  [ROAD] road_ambient/{log_path.name}: {len(df):,} frames")
            sources.append(("road_ambient", df))
    else:
        print(f"  [INFO] ROAD dataset not found at {ROAD_ROOT} — skipping")

    # Car-Hacking Dataset — normal-traffic rows (flag='R') from all 4 CSVs.
    # Each CSV has 3-4M rows; sample to CHD_FRAMES_PER_FILE for balance.
    CHD_FRAMES_PER_FILE = 300_000
    if CAR_HACKING_ROOT.exists():
        for csv_name in ("DoS_dataset.csv", "Fuzzy_dataset.csv", "RPM_dataset.csv", "gear_dataset.csv"):
            csv_path = CAR_HACKING_ROOT / csv_name
            if not csv_path.exists():
                continue
            df = load_car_hacking_csv(csv_path)
            if df is None:
                print(f"  [SKIP] car_hacking/{csv_name}")
                continue
            if len(df) > CHD_FRAMES_PER_FILE:
                df = df.sample(n=CHD_FRAMES_PER_FILE, random_state=42).reset_index(drop=True)
            print(f"  [CHD] car_hacking/{csv_name}: {len(df):,} normal frames")
            sources.append(("car_hacking_normal", df))
    else:
        print(f"  [INFO] Car-Hacking dataset not found at {CAR_HACKING_ROOT} — skipping")

    return sources


def _map_states(df: pd.DataFrame, labels: np.ndarray) -> dict[int, str]:
    tmp = df.copy()
    tmp["cluster"] = labels
    stats = tmp.groupby("cluster")[["rolling_std_time_diff", "byte_diff", "changed_bytes_count"]].mean()
    order = stats.sort_values(["rolling_std_time_diff", "byte_diff", "changed_bytes_count"]).index.tolist()
    return {order[0]: "parking", order[1]: "idle", order[2]: "driving"}


def _fit_state_models(df: pd.DataFrame, out_dir: Path) -> dict[str, float]:
    out_dir.mkdir(parents=True, exist_ok=True)
    thresholds: dict[str, float] = {}
    threshold_meta: dict[str, dict[str, float | str]] = {}
    feature_sets: dict[str, list[str]] = {}
    for state in STATE_NAMES:
        s_df = df[df["state"] == state]
        if len(s_df) < MIN_ROWS_PER_STATE:
            continue
        use_feats = [c for c in FEATURES if c in s_df.columns and c != "can_id" and not c.startswith("b") and float(s_df[c].std()) > 1e-6]
        assert not any(col.startswith("b") for col in use_feats)
        if len(use_feats) < 3:
            continue
        raw_x = s_df[use_feats].to_numpy(dtype=np.float32)
        selector = VarianceThreshold(threshold=1e-6)
        x_sel = selector.fit_transform(raw_x)
        support = selector.get_support()
        use_feats = [f for f, keep in zip(use_feats, support) if keep]
        if len(use_feats) < 3:
            continue
        scaler = RobustScaler()
        x = scaler.fit_transform(x_sel.astype(np.float32, copy=False))
        model = IsolationForest(n_estimators=200, contamination=CONTAMINATION, random_state=42, n_jobs=1)
        model.fit(x)
        scores = model.decision_function(x)
        median_score = float(np.median(scores))
        mad = float(np.median(np.abs(scores - median_score)))
        if mad < 1e-6:
            th = float(np.quantile(scores, 0.02))
            method = "p02_fallback_low_mad"
            print(f"[WARN] {out_dir.name}/{state}: MAD near zero, using percentile fallback")
        else:
            th = float(median_score - (ROBUST_K * mad))
            method = "median_minus_kmad"
        print(
            f"[INFO] {out_dir.name}/{state} "
            f"median={median_score:.6f} mad={mad:.6f} threshold={th:.6f} "
            f"min={float(np.min(scores)):.6f} max={float(np.max(scores)):.6f}"
        )
        joblib.dump(model, out_dir / f"model_{state}.joblib")
        joblib.dump(scaler, out_dir / f"scaler_{state}.joblib")
        thresholds[state] = th
        threshold_meta[state] = {
            "method": method,
            "k": ROBUST_K,
            "median_score": median_score,
            "mad": mad,
            "threshold": th,
            "score_min": float(np.min(scores)),
            "score_max": float(np.max(scores)),
        }
        feature_sets[state] = use_feats
        # Optional score histogram for debugging
        SCORE_DIST_ROOT.mkdir(parents=True, exist_ok=True)
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.hist(scores, bins=60, color="#2a9d8f", alpha=0.85)
        ax.axvline(th, color="#dc2626", linestyle="--", linewidth=2)
        ax.set_title(f"{out_dir.name} {state} score distribution")
        ax.set_xlabel("decision_function score")
        ax.set_ylabel("count")
        fig.tight_layout()
        fig.savefig(SCORE_DIST_ROOT / f"{out_dir.name}_{state}.png", dpi=120)
        plt.close(fig)
    (out_dir / "thresholds.json").write_text(json.dumps(thresholds, indent=2), encoding="utf-8")
    (out_dir / "threshold_meta.json").write_text(json.dumps(threshold_meta, indent=2), encoding="utf-8")
    (out_dir / "feature_sets.json").write_text(json.dumps(feature_sets, indent=2), encoding="utf-8")
    return thresholds


def _plot_pca(
    df: pd.DataFrame,
    model_dir: Path,
    label_prefix: str,
    sample_size: int = 10000,
) -> None:
    thresholds, feature_sets = _safe_load_state_artifacts(model_dir)
    if not thresholds or not feature_sets:
        return
    PCA_OUT_ROOT.mkdir(parents=True, exist_ok=True)

    for state in STATE_NAMES:
        model_path = model_dir / f"model_{state}.joblib"
        scaler_path = model_dir / f"scaler_{state}.joblib"
        if not (model_path.exists() and scaler_path.exists() and state in thresholds and state in feature_sets):
            continue

        sdf = df[df["state"] == state]
        if sdf.empty:
            continue
        if len(sdf) > sample_size:
            sdf = sdf.sample(n=sample_size, random_state=42)

        feats = feature_sets[state]
        if not all(c in sdf.columns for c in feats):
            continue

        model = joblib.load(model_path)
        scaler = joblib.load(scaler_path)
        x = sdf[feats].to_numpy(dtype=np.float32, copy=True)
        x_scaled = scaler.transform(x)
        scores = model.decision_function(x_scaled)
        labels = scores < float(thresholds[state])

        pca = PCA(n_components=2, random_state=42)
        comps = pca.fit_transform(x_scaled)

        fig, ax = plt.subplots(figsize=(9, 6))
        normal_mask = ~labels
        anomaly_mask = labels
        ax.scatter(comps[normal_mask, 0], comps[normal_mask, 1], s=8, alpha=0.35, c="#2563eb", label="normal")
        ax.scatter(comps[anomaly_mask, 0], comps[anomaly_mask, 1], s=12, alpha=0.8, c="#dc2626", label="anomaly")
        ax.set_title(f"{label_prefix} - {state}")
        ax.set_xlabel("PCA1")
        ax.set_ylabel("PCA2")
        ax.legend()
        ax.grid(alpha=0.2)
        fig.tight_layout()
        out_path = PCA_OUT_ROOT / f"pca_{label_prefix}_{state}.png"
        fig.savefig(out_path, dpi=150)
        plt.close(fig)


def train() -> None:
    MODEL_ROOT.mkdir(parents=True, exist_ok=True)

    # ── 1. Kaggle normal baseline ────────────────────────────────────────────
    if not KAGGLE_NORMAL_PATH.exists():
        raise FileNotFoundError(f"Kaggle normal dataset not found: {KAGGLE_NORMAL_PATH}")
    print_progress("TRAIN", "kaggle", 1, 1, KAGGLE_NORMAL_PATH.name)
    kaggle_raw = load_kaggle_dataset(KAGGLE_NORMAL_PATH)
    kaggle_df, _, _ = preprocess_pipeline(kaggle_raw, scaler=None, fit=True)
    if kaggle_df.empty:
        raise ValueError("No usable training data after preprocessing Kaggle dataset")
    kaggle_df["vehicle"] = "kaggle_normal"
    kaggle_df = kaggle_df.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    print(f"  [kaggle_normal] {len(kaggle_df):,} feature rows")

    # ── 2. Real EV CAN logs (CSV) ────────────────────────────────────────────
    print_progress("TRAIN", "ev_logs", 1, 1, "loading EV-CANlogs CSV data")
    ev_sources = load_all_ev_logs()

    # ── 2b. Real EV MF4 logs (CANedge Train/) ────────────────────────────────
    print_progress("TRAIN", "mf4_logs", 1, 1, "loading MF4 CANedge recordings")
    mf4_sources = load_all_mf4_logs()

    ev_dfs: list[pd.DataFrame] = []
    for vname, ev_raw in (ev_sources + mf4_sources):
        try:
            ev_feat, _, _ = preprocess_pipeline(ev_raw, scaler=None, fit=True)
        except ValueError as exc:
            print(f"  [SKIP] {vname}: {exc}")
            continue
        if ev_feat.empty:
            print(f"  [SKIP] {vname}: empty after feature engineering")
            continue
        ev_feat["vehicle"] = vname
        ev_feat = ev_feat.replace([np.inf, -np.inf], np.nan).fillna(0.0)
        print(f"  [{vname}] {len(ev_feat):,} feature rows")
        ev_dfs.append(ev_feat)

    # ── 3. Combine all sources ───────────────────────────────────────────────
    all_df = pd.concat([kaggle_df] + ev_dfs, ignore_index=True)
    total_rows = len(all_df)
    n_sources = 1 + len(ev_dfs)
    print(f"\n[INFO] Combined dataset: {total_rows:,} rows from {n_sources} sources\n")

    # ── 4. KMeans vehicle-state classifier ──────────────────────────────────
    print_progress("TRAIN", "kmeans", 1, 1, "fitting state clusters on combined data")
    state_scaler = RobustScaler()
    avail_state_feats = [f for f in STATE_FEATS if f in all_df.columns]
    x_state = state_scaler.fit_transform(all_df[avail_state_feats].to_numpy(dtype=np.float32))
    kmeans_model = KMeans(n_clusters=3, random_state=42, n_init=20)
    labels = kmeans_model.fit_predict(x_state)
    mapping = _map_states(all_df, labels)
    all_df["state"] = pd.Series(labels).map(mapping)
    for state in STATE_NAMES:
        n = int((all_df["state"] == state).sum())
        pct = 100.0 * n / total_rows
        print(f"  [{state}] {n:,} rows ({pct:.1f}%)")
    joblib.dump(state_scaler, MODEL_ROOT / "state_scaler.joblib")
    joblib.dump(kmeans_model, MODEL_ROOT / "kmeans_state_model.joblib")
    (MODEL_ROOT / "state_mapping.json").write_text(
        json.dumps({str(k): v for k, v in mapping.items()}, indent=2), encoding="utf-8"
    )
    print()

    # ── 5. General models (all vehicles combined) ────────────────────────────
    print_progress("TRAIN", "general", 1, 1, "fitting general state models")
    general_dir = MODEL_ROOT / "general"
    _fit_state_models(all_df, general_dir)
    print()

    # ── 6. Vehicle-specific models ───────────────────────────────────────────
    vehicle_groups = list(all_df.groupby("vehicle", sort=False))
    total_vehicles = len(vehicle_groups)
    for idx, (vehicle, vdf) in enumerate(vehicle_groups, start=1):
        can_ids = vdf["can_id"].unique()
        print_progress("TRAIN", vehicle, idx, total_vehicles, f"{len(can_ids)} CAN IDs")
        _fit_state_models(vdf, MODEL_ROOT / vehicle)
    print()

    # ── 7. PCA diagnostics ───────────────────────────────────────────────────
    print_progress("TRAIN", "pca", 1, 1, "generating diagnostics")
    _plot_pca(all_df, general_dir, "general")
    for vehicle, vdf in all_df.groupby("vehicle", sort=False):
        _plot_pca(vdf, MODEL_ROOT / vehicle, vehicle)
    print()

    trained = [s for s in STATE_NAMES if (general_dir / f"model_{s}.joblib").exists()]
    print(f"[INFO] Training complete — states trained: {trained}")
    print(f"[INFO] Models saved -> {MODEL_ROOT}")


def _safe_load_state_artifacts(root: Path) -> tuple[dict[str, float], dict[str, list[str]]]:
    th = {}
    fs = {}
    th_path = root / "thresholds.json"
    fs_path = root / "feature_sets.json"
    if th_path.exists():
        th = json.loads(th_path.read_text(encoding="utf-8"))
    if fs_path.exists():
        fs = json.loads(fs_path.read_text(encoding="utf-8"))
    return th, fs


def infer(df_features: pd.DataFrame, vehicle: str) -> pd.DataFrame:
    vehicle_key = vehicle.strip().lower().replace(" ", "_")
    out = df_features.copy()
    for c in STATE_FEATS:
        if c not in out.columns:
            out[c] = 0.0
    out[STATE_FEATS] = out[STATE_FEATS].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    state_scaler = joblib.load(MODEL_ROOT / "state_scaler.joblib")
    kmeans_model = joblib.load(MODEL_ROOT / "kmeans_state_model.joblib")
    mapping = {int(k): v for k, v in json.loads((MODEL_ROOT / "state_mapping.json").read_text(encoding="utf-8")).items()}
    x_state = state_scaler.transform(out[STATE_FEATS].to_numpy(dtype=np.float32))
    labels = kmeans_model.predict(x_state)
    out["state"] = [mapping[int(c)] for c in labels]
    out["anomaly_score"] = 0.0
    out["smoothed_score"] = 0.0
    out["is_anomaly"] = 0

    general_dir = MODEL_ROOT / "general"
    vehicle_dir = MODEL_ROOT / vehicle_key
    g_th, g_fs = _safe_load_state_artifacts(general_dir)
    v_th, v_fs = _safe_load_state_artifacts(vehicle_dir)

    for state in STATE_NAMES:
        mask = out["state"] == state
        if not mask.any():
            continue
        use_vehicle = (
            (vehicle_dir / f"model_{state}.joblib").exists()
            and (vehicle_dir / f"scaler_{state}.joblib").exists()
            and state in v_th
            and state in v_fs
        )
        chosen = vehicle_dir if use_vehicle else general_dir
        th_map = v_th if use_vehicle else g_th
        fs_map = v_fs if use_vehicle else g_fs
        if not ((chosen / f"model_{state}.joblib").exists() and (chosen / f"scaler_{state}.joblib").exists() and state in th_map and state in fs_map):
            # safe fallback: if neither exists, keep normal
            print(f"[STATE] {state}")
            print(f"[VEHICLE] {vehicle_key}")
            print("[MODEL USED] none")
            continue
        model = joblib.load(chosen / f"model_{state}.joblib")
        scaler = joblib.load(chosen / f"scaler_{state}.joblib")
        feats = fs_map[state]
        for c in feats:
            if c not in out.columns:
                out[c] = 0.0
        assert not any(col.startswith("b") for col in feats)
        x = out.loc[mask, feats].to_numpy(dtype=np.float32)
        scores = model.decision_function(scaler.transform(x))
        threshold = float(th_map[state])
        smoothed = pd.Series(scores).rolling(5, min_periods=1).mean().to_numpy()
        below = smoothed < threshold
        persistent = (
            pd.Series(below.astype(np.int8))
            .rolling(5, min_periods=1)
            .sum()
            .to_numpy() >= 3
        )
        out.loc[mask, "anomaly_score"] = scores
        out.loc[mask, "smoothed_score"] = smoothed
        out.loc[mask, "is_anomaly"] = persistent.astype(np.int8)
        if len(smoothed) > 0:
            print(
                f"[DEBUG] {vehicle_key}/{state} "
                f"smoothed={float(smoothed[-1]):.6f} "
                f"threshold={threshold:.6f} "
                f"decision={'anomaly' if bool(persistent[-1]) else 'normal'}"
            )
        print(f"[STATE] {state}")
        print(f"[VEHICLE] {vehicle_key}")
        print(f"[MODEL USED] {'vehicle' if use_vehicle else 'general'}")
    return out


if __name__ == "__main__":
    train()
