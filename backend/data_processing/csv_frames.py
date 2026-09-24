"""Header-aware CSV frame parser for uploaded CAN logs.

Used by ``/analyze`` (``server._try_parse_as_csv``) when ``CanLogParser`` finds
no ``ID#DATA`` tokens, i.e. for column-format CSV exports.

Columns are located by header *name*, never by position. The previous
implementation renamed unknown header columns positionally, so an asammdf MF4
export (``timestamps, ..BusChannel, ..ID, ..IDE, ..DLC, ..DataLength,
..DataBytes, ...``) had its BusChannel read as the CAN ID and unrelated columns
read as payload bytes; SavvyCAN exports lost their D1..D8 bytes the same way.

The C# importer (Services/CsvCanLayout.cs) applies the same rules, so desktop
playback and ML analysis see identical frames.

Numeric encoding per column: evidence in the data decides (hex letters or 0x
prefix -> hex; zero-padded identifiers such as SavvyCAN "0000012D" -> hex;
identifiers that would exceed 29 bits read as hex -> decimal; byte tokens of
three digits or numpy-style ``[ 3 34 ...]`` arrays -> decimal). Without
evidence the previous behaviour is kept: hex, except asammdf exports whose
integer IDs and uint8 arrays are decimal by construction.

Headerless files and headers without recognisable timestamp/ID/payload columns
keep the previous positional behaviour unchanged.
"""
from __future__ import annotations

import io
import re

import pandas as pd

MAX_CAN_ID = 0x1FFFFFFF
OUTPUT_COLUMNS = ["timestamp", "can_id", "b0", "b1", "b2", "b3", "b4", "b5", "b6", "b7"]

_TIMESTAMP = ("timestamp", "timestamps", "time", "ts")
_ID = ("id", "canid", "arbitrationid", "arbid", "identifier", "msgid", "messageid")
_DATA_ARRAY = ("databytes", "data", "payload", "bytes", "databyte")
_LENGTH = ("datalength", "len", "length", "dlc")  # DataLength = byte count; DLC = code
_ZERO_BASED = re.compile(r"^(?:b|byte|data)(\d+)$")
_ONE_BASED = re.compile(r"^d(\d+)$")
_SAMPLE_ROWS = 500

# OUTPUT_COLUMNS as _normalize() renders a header row ("can_id" -> "canid"),
# used to recognise this project's own MF4-converter output exactly.
_CANONICAL_MF4_COLUMNS = ["timestamp", "canid", "b0", "b1", "b2", "b3", "b4", "b5", "b6", "b7"]


def parse_csv_frames(raw: bytes, source_name: str = "") -> pd.DataFrame:
    """Parse column-format CSV bytes into ``timestamp, can_id, b0..b7, source_file``."""
    text = raw.decode("utf-8", errors="ignore")
    lines = [
        line for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith(("#", "//", ";"))
    ]
    if not lines:
        return pd.DataFrame()

    header = split_fields(lines[0])
    if _is_number(header[0]):
        return _legacy_parse(text, source_name, headerless=True)

    layout = _layout_from_header(lines[0], header)
    if layout is None:
        return _legacy_parse(text, source_name, headerless=False)

    rows = [split_fields(line) for line in lines[1:]]
    _decide_radix(layout, rows[:_SAMPLE_ROWS])

    records = []
    for fields in rows:
        record = _parse_row(layout, fields)
        if record is not None:
            records.append(record)

    df = pd.DataFrame(records, columns=OUTPUT_COLUMNS)
    df["source_file"] = source_name
    return df


# ── layout ───────────────────────────────────────────────────────────────────

def _layout_from_header(header_line: str, header: list[str]) -> dict | None:
    names = [_normalize(h) for h in header]
    ts_index = _first(names, _TIMESTAMP)
    id_index = _first(names, _ID)
    if ts_index < 0 or id_index < 0:
        return None

    byte_columns: list[tuple[int, int, bool]] = []
    for column, name in enumerate(names):
        zero = _ZERO_BASED.match(name)
        if zero:
            byte_columns.append((int(zero.group(1)), column, False))
            continue
        one = _ONE_BASED.match(name)
        if one:
            byte_columns.append((int(one.group(1)) - 1, column, True))

    array_index = _first(names, _DATA_ARRAY)
    if array_index < 0 and not byte_columns:
        return None

    # Radix when the data itself carries no evidence either way (_decide_radix
    # overrides this whenever it finds any).
    #
    # Two formats are known to be decimal at the source. An asammdf MF4 export
    # writes decimal, and so does this project's own MF4 converter, whose output
    # is exactly `timestamp,can_id,b0..b7` and whose _normalize_can_id() does
    # int(float(text)). Identifiers in that file - 2028, 2020, 25 - are all valid
    # hex that stay inside MAX_CAN_ID, so nothing contradicts a hex default and
    # UDS response id 0x7EC was being read as 0x2028.
    #
    # The match is on the exact canonical column list, not merely on the presence
    # of a `can_id` column: replay logs carry the same first ten columns followed
    # by `state,attack_type` and are hex, and they must keep reading as hex.
    asammdf = "can_dataframe" in header_line.lower()
    canonical_mf4 = names == _CANONICAL_MF4_COLUMNS
    default = "dec" if (asammdf or canonical_mf4) else "hex"
    return {
        "ts": ts_index,
        "id": id_index,
        "len": _first(names, _LENGTH),
        "array": array_index,
        "bytes": [column for _, column, _ in sorted(byte_columns)],
        "id_radix": default,
        "byte_radix": default,
    }


def _decide_radix(layout: dict, rows: list[list[str]]) -> None:
    id_hex = id_dec = byte_hex = byte_dec = False
    for fields in rows:
        if layout["id"] < len(fields):
            value = _unquote(fields[layout["id"]])
            if value:
                if value.lower().startswith("0x") or _has_hex_letter(value) or (
                    len(value) >= 3 and value[0] == "0" and value.isdigit()
                ):
                    id_hex = True
                elif value.isdigit() and int(value, 16) > MAX_CAN_ID:
                    id_dec = True

        for token in _payload_tokens(layout, fields):
            if token.lower().startswith("0x") or _has_hex_letter(token):
                byte_hex = True
            elif len(token) >= 3 and token.isdigit():
                byte_dec = True

        if layout["array"] >= 0 and layout["array"] < len(fields) and _unquote(fields[layout["array"]]).startswith("["):
            byte_dec = True

    if id_hex:
        layout["id_radix"] = "hex"
    elif id_dec:
        layout["id_radix"] = "dec"
    if byte_hex:
        layout["byte_radix"] = "hex"
    elif byte_dec:
        layout["byte_radix"] = "dec"


def _parse_row(layout: dict, fields: list[str]) -> list | None:
    if layout["ts"] >= len(fields) or layout["id"] >= len(fields):
        return None
    try:
        timestamp = float(_unquote(fields[layout["ts"]]))
    except ValueError:
        return None

    can_id = _to_int(_unquote(fields[layout["id"]]), layout["id_radix"], MAX_CAN_ID)
    if can_id is None:
        return None

    length = None
    if 0 <= layout["len"] < len(fields):
        try:
            length = max(0, int(_unquote(fields[layout["len"]])))
        except ValueError:
            length = None

    payload: list[int] = []
    for token in _payload_tokens(layout, fields):
        if length is not None and len(payload) >= length:
            break
        value = _to_int(token, layout["byte_radix"], 0xFF)
        if value is None:
            return None  # malformed payload: drop the row rather than guess
        payload.append(value)

    payload = (payload + [0] * 8)[:8]
    return [timestamp, can_id, *payload]


def _payload_tokens(layout: dict, fields: list[str]):
    if layout["array"] >= 0:
        if layout["array"] >= len(fields):
            return
        text = _unquote(fields[layout["array"]]).strip("[](){} ")
        tokens = [t for t in re.split(r"[\s,;]+", text) if t]
        if len(tokens) == 1 and len(tokens[0]) > 2 and layout["byte_radix"] == "hex" and all(
            c in "0123456789abcdefABCDEF" for c in tokens[0]
        ):
            for i in range(0, len(tokens[0]) - 1, 2):
                yield tokens[0][i:i + 2]
            return
        yield from tokens
        return

    for column in layout["bytes"]:
        if column >= len(fields):
            return
        token = _unquote(fields[column])
        if not token:
            return  # trailing empty columns (SavvyCAN rows end with ",")
        yield token


# ── previous behaviour, kept verbatim for headerless / unrecognised files ───

def _legacy_parse(text: str, source_name: str, headerless: bool) -> pd.DataFrame:
    buf = io.StringIO(text)
    if headerless:
        df = pd.read_csv(buf, header=None, names=OUTPUT_COLUMNS, low_memory=False)
    else:
        df = pd.read_csv(buf, low_memory=False)
        df.columns = [c.strip().lower() for c in df.columns]
        for i, name in enumerate(OUTPUT_COLUMNS):
            if name not in df.columns and i < len(df.columns):
                df.rename(columns={df.columns[i]: name}, inplace=True)

    if not set(OUTPUT_COLUMNS).issubset(set(df.columns)):
        return pd.DataFrame()

    df["can_id"] = df["can_id"].apply(_legacy_hex_or_int)
    df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce")
    for column in OUTPUT_COLUMNS[2:]:
        df[column] = df[column].apply(_legacy_hex_or_int)
    df = df.dropna(subset=["timestamp"])
    df["source_file"] = source_name
    return df[OUTPUT_COLUMNS + ["source_file"]]


def _legacy_hex_or_int(val: object) -> int:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return 0
    s = str(val).strip().lower()
    try:
        return int(s, 16)
    except ValueError:
        try:
            return int(float(s))
        except (ValueError, TypeError):
            return 0


# ── helpers ──────────────────────────────────────────────────────────────────

def split_fields(line: str) -> list[str]:
    """Split on commas outside double quotes and [..] / (..) groups."""
    fields, current, in_quotes, depth = [], [], False, 0
    for char in line:
        if char == '"':
            in_quotes = not in_quotes
            current.append(char)
        elif char in "[(" and not in_quotes:
            depth += 1
            current.append(char)
        elif char in "])" and not in_quotes:
            depth = max(0, depth - 1)
            current.append(char)
        elif char == "," and not in_quotes and depth == 0:
            fields.append("".join(current))
            current = []
        else:
            current.append(char)
    fields.append("".join(current))
    return fields


def _to_int(text: str, radix: str, maximum: int) -> int | None:
    if not text:
        return None
    try:
        if text.lower().startswith("0x"):
            value = int(text[2:], 16)
        elif radix == "hex":
            value = int(text, 16)
        else:
            value = int(text, 10)
    except ValueError:
        return None
    return value if 0 <= value <= maximum else None


def _normalize(name: str) -> str:
    name = _unquote(name).rsplit(".", 1)[-1]
    return re.sub(r"[^0-9a-z]", "", name.lower())


def _first(names: list[str], candidates: tuple[str, ...]) -> int:
    for candidate in candidates:
        if candidate in names:
            return names.index(candidate)
    return -1


def _unquote(value: str) -> str:
    return value.strip().strip('"').strip()


def _has_hex_letter(value: str) -> bool:
    return any(c in "abcdefABCDEF" for c in value)


def _is_number(value: str) -> bool:
    try:
        float(_unquote(value))
        return True
    except ValueError:
        return False
