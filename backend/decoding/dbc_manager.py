"""DBC-based CAN signal decoder.

Loads DBC files via cantools and decodes raw CAN frames into named signals
with engineering values (voltage in V, SOC in %, temperature in °C, etc.).

Usage:
    from backend.decoding.dbc_manager import DBCManager
    mgr = DBCManager()
    signals = mgr.decode("nissan_leaf", can_id=0x79C, payload=bytes([0x02, 0xA0, ...]))
    # → [DecodedSignal(name="Battery_Voltage", value=394.5, unit="V", ...), ...]
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import cantools
import cantools.database

from backend.decoding.vehicle_profiles import VehicleProfile, get as get_profile, PROFILES

logger = logging.getLogger(__name__)


@dataclass
class DecodedSignal:
    name: str
    value: float | int | str
    unit: str
    raw: int
    out_of_range: bool
    min_val: float | None
    max_val: float | None
    system: str          # e.g. "Battery", "Motor", "HVAC"


class DBCManager:
    """Thread-safe DBC loader and frame decoder.

    Lazily loads DBC databases on first use per vehicle, then caches them.
    Falls back gracefully when no DBC is available or a CAN-ID is not defined.
    """

    def __init__(self) -> None:
        # vehicle_id → list of cantools.db.Database
        self._dbs: dict[str, list[cantools.database.Database]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def decode(
        self,
        vehicle_id: str,
        can_id: int,
        payload: bytes | list[int],
    ) -> list[DecodedSignal]:
        """Decode a CAN frame.  Returns [] if vehicle unknown or CAN-ID not in DBC."""
        dbs = self._get_dbs(vehicle_id)
        if not dbs:
            return []

        raw_bytes = bytes(payload) if not isinstance(payload, bytes) else payload

        for db in dbs:
            try:
                msg = db.get_message_by_frame_id(can_id)
            except KeyError:
                continue

            try:
                decoded: dict[str, Any] = msg.decode(raw_bytes, decode_choices=False)
            except Exception as exc:
                logger.debug("cantools decode error CAN_ID=0x%X: %s", can_id, exc)
                continue

            results: list[DecodedSignal] = []
            for sig in msg.signals:
                val = decoded.get(sig.name)
                if val is None:
                    continue

                # Determine system group from message name prefix
                system = msg.name.split("_")[0] if "_" in msg.name else msg.name

                raw_int = 0
                try:
                    raw_int = int((float(val) - (sig.offset or 0)) / (sig.scale or 1))
                except Exception:
                    pass

                min_v = float(sig.minimum) if sig.minimum is not None else None
                max_v = float(sig.maximum) if sig.maximum is not None else None
                oor = False
                if min_v is not None and max_v is not None:
                    try:
                        oor = not (min_v <= float(val) <= max_v)
                    except Exception:
                        pass

                results.append(DecodedSignal(
                    name=sig.name,
                    value=round(float(val), 4) if isinstance(val, (int, float)) else val,
                    unit=sig.unit or "",
                    raw=raw_int,
                    out_of_range=oor,
                    min_val=min_v,
                    max_val=max_v,
                    system=system,
                ))
            return results  # matched first DB that knows this CAN-ID

        return []  # no DB matched

    def known_can_ids(self, vehicle_id: str) -> list[int]:
        """Return all CAN-IDs defined in the vehicle's DBC files."""
        dbs = self._get_dbs(vehicle_id)
        ids: list[int] = []
        for db in dbs:
            ids.extend(msg.frame_id for msg in db.messages)
        return sorted(set(ids))

    def describe_message(self, vehicle_id: str, can_id: int) -> str | None:
        """Return the message name for a CAN-ID, or None if unknown."""
        for db in self._get_dbs(vehicle_id):
            try:
                return db.get_message_by_frame_id(can_id).name
            except KeyError:
                continue
        return None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_dbs(self, vehicle_id: str) -> list[cantools.database.Database]:
        if vehicle_id in self._dbs:
            return self._dbs[vehicle_id]

        profile = get_profile(vehicle_id)
        if profile is None:
            logger.warning("Unknown vehicle_id '%s'", vehicle_id)
            self._dbs[vehicle_id] = []
            return []

        loaded: list[cantools.database.Database] = []

        # Load UDS DBCs first (most complete for our CSS Electronics logs)
        for dbc_path in profile.uds_dbc:
            db = _load_dbc(dbc_path)
            if db is not None:
                loaded.append(db)

        # Then raw broadcast DBCs
        for dbc_path in profile.raw_dbc:
            if dbc_path.suffix.lower() == ".dbc":
                db = _load_dbc(dbc_path)
                if db is not None:
                    loaded.append(db)

        if not loaded:
            logger.warning("No DBC files loaded for vehicle '%s'", vehicle_id)

        self._dbs[vehicle_id] = loaded
        return loaded


def _load_dbc(path: Path) -> cantools.database.Database | None:
    if not path.exists():
        logger.warning("DBC file not found: %s", path)
        return None
    try:
        db = cantools.database.load_file(str(path), strict=False)
        logger.info("Loaded DBC: %s (%d messages)", path.name, len(db.messages))
        return db
    except Exception as exc:
        logger.error("Failed to load DBC %s: %s", path.name, exc)
        return None


# Module-level singleton — shared by server.py and offline analyzer
_manager: DBCManager | None = None


def get_manager() -> DBCManager:
    global _manager
    if _manager is None:
        _manager = DBCManager()
    return _manager
