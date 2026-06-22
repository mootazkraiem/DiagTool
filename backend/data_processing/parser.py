from __future__ import annotations

import io
import re
from typing import Any
import pandas as pd

SUPPORTED_SUFFIXES: set[str] = {".log", ".txt", ".trc", ".asc", ".csv", ".crtd"}
CAN_ID_DATA_PATTERN = re.compile(r"(?P<can_id>[0-9A-Fa-f]{2,8})#(?P<data>[0-9A-Fa-f]*)")

class ParseStats:
    def __init__(self) -> None:
        self.lines_total = 0
        self.lines_parsed = 0
        self.lines_skipped = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "lines_total": self.lines_total,
            "lines_parsed": self.lines_parsed,
            "lines_skipped": self.lines_skipped,
        }

class CanLogParser:
    """Vehicle-agnostic CAN parser with support for common candump/ASC/CSV-like variants."""

    @staticmethod
    def parse_text(log_text: str, source_name: str = "uploaded.log") -> tuple[pd.DataFrame, ParseStats]:
        stats = ParseStats()
        rows: list[dict[str, Any]] = []
        for line in log_text.splitlines():
            stats.lines_total += 1
            parsed = CanLogParser._parse_line(line)
            if parsed is None:
                stats.lines_skipped += 1
                continue
            parsed["source_file"] = source_name
            rows.append(parsed)
            stats.lines_parsed += 1
        return pd.DataFrame(rows), stats

    @staticmethod
    def parse_stream(stream: io.TextIOBase, source_name: str, max_lines: int = 0) -> tuple[pd.DataFrame, ParseStats]:
        stats = ParseStats()
        rows: list[dict[str, Any]] = []
        for idx, line in enumerate(stream):
            if max_lines and idx >= max_lines:
                break
            stats.lines_total += 1
            parsed = CanLogParser._parse_line(line)
            if parsed is None:
                stats.lines_skipped += 1
                continue
            parsed["source_file"] = source_name
            rows.append(parsed)
            stats.lines_parsed += 1
        return pd.DataFrame(rows), stats

    @staticmethod
    def _parse_line(line: str) -> dict[str, Any] | None:
        text = line.strip()
        if not text:
            return None

        if text.startswith("#") or text.startswith("//") or text.startswith(";"):
            return None

        parsed = CanLogParser._parse_candump_style(text)
        if parsed:
            return parsed

        parsed = CanLogParser._parse_asc_style(text)
        if parsed:
            return parsed

        parsed = CanLogParser._parse_csv_like(text)
        if parsed:
            return parsed

        parsed = CanLogParser._parse_tab_separated(text)
        if parsed:
            return parsed

        return None

    @staticmethod
    def _parse_candump_style(text: str) -> dict[str, Any] | None:
        patterns = [
            re.compile(
                r"^\((?P<ts>[-+]?\d+(?:\.\d+)?)\)\s+"
                r"(?P<iface>\S+)\s+"
                r"(?P<can_id>[0-9A-Fa-f]+)#(?P<data>[0-9A-Fa-f]*)\s*$"
            ),
            re.compile(
                r"^(?P<ts>[-+]?\d+(?:\.\d+)?)\s+"
                r"(?P<iface>\S+)\s+"
                r"(?P<can_id>[0-9A-Fa-f]+)#(?P<data>[0-9A-Fa-f]*)\s*$"
            ),
        ]
        for pattern in patterns:
            match = pattern.match(text)
            if not match:
                continue
            return _build_row(
                timestamp=float(match.group("ts")),
                interface=match.group("iface"),
                can_id_hex=match.group("can_id"),
                data_hex=match.group("data"),
            )
        return None

    @staticmethod
    def _parse_asc_style(text: str) -> dict[str, Any] | None:
        match = re.match(
            r"^(?P<ts>\d+(?:\.\d+)?)\s+"
            r"(?P<channel>\S+)\s+"
            r"(?P<can_id>[0-9A-Fa-f]+)\s+"
            r"(?:Rx|Tx|rx|tx)\s+d\s+(?P<dlc>\d+)\s+(?P<payload>.+)$",
            text,
        )
        if not match:
            return None
        dlc = int(match.group("dlc"))
        payload = match.group("payload").strip().split()
        bytes_hex = "".join(token.zfill(2) for token in payload[:dlc] if re.fullmatch(r"[0-9A-Fa-f]{1,2}", token))
        return _build_row(
            timestamp=float(match.group("ts")),
            interface=str(match.group("channel")),
            can_id_hex=str(match.group("can_id")),
            data_hex=bytes_hex,
        )

    @staticmethod
    def _parse_csv_like(text: str) -> dict[str, Any] | None:
        token_match = CAN_ID_DATA_PATTERN.search(text)
        if not token_match:
            return None
        ts_match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
        if not ts_match:
            return None
        return _build_row(
            timestamp=float(ts_match.group(0)),
            interface="can",
            can_id_hex=token_match.group("can_id"),
            data_hex=token_match.group("data"),
        )

    @staticmethod
    def _parse_tab_separated(text: str) -> dict[str, Any] | None:
        # Parse tab-separated format like: 1 0 1 RX 2124377  0x000003a0 8 0xff ff c0 ff ff ff ff fd
        parts = text.strip().split('\t')
        if len(parts) < 9:
            return None
        
        try:
            # Skip header line
            if parts[0] == 'ParserFlags' or not parts[4].isdigit():
                return None
            
            timestamp = float(parts[4]) / 1000.0  # Convert microseconds to seconds
            can_id_hex = parts[6].replace('0x', '')
            data_str = parts[8]
            # Data format: 0xff ff c0 ff ff ff ff fd
            data_parts = data_str.replace('0x', '').split()
            data_hex = ''.join(data_parts)
            
            return _build_row(
                timestamp=timestamp,
                interface="can",
                can_id_hex=can_id_hex,
                data_hex=data_hex,
            )
        except (ValueError, IndexError):
            return None

def _build_row(timestamp: float, interface: str, can_id_hex: str, data_hex: str) -> dict[str, Any]:
    byte_values = _hex_to_bytes(data_hex)
    row: dict[str, Any] = {
        "timestamp": float(timestamp),
        "interface": str(interface),
        "can_id_hex": f"0x{str(can_id_hex).upper()}",
        "can_id": int(str(can_id_hex), 16),
        "data_hex": str(data_hex).upper(),
    }
    for index in range(8):
        row[f"b{index}"] = int(byte_values[index])
    return row

def _hex_to_bytes(data_hex: str) -> list[int]:
    text = data_hex.strip()
    if len(text) % 2 == 1:
        text = f"0{text}"
    values = [int(text[i : i + 2], 16) for i in range(0, len(text), 2) if text]
    values = values[:8]
    if len(values) < 8:
        values.extend([0] * (8 - len(values)))
    return values
