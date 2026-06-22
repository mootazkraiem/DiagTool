"""Vehicle profile registry.

Maps vehicle_id strings to their DBC files, CAN bitrate, and transmit-list
(UDS poll config used by CANedge loggers).

DBC_BASE  → assets/dbc_files/          (UDS response DBC files from CSS Electronics)
RAW_BASE  → assets/EV-CANlogs-main/    (raw broadcast DBC files from EV community)
TX_BASE   → assets/transmit_lists/     (CANedge UDS transmit lists)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DBC_BASE     = _PROJECT_ROOT / "assets" / "dbc_files"
_RAW_BASE     = _PROJECT_ROOT / "assets" / "EV-CANlogs-main"
_TX_BASE      = _PROJECT_ROOT / "assets" / "transmit_lists"


@dataclass(frozen=True)
class VehicleProfile:
    id: str
    name: str
    bitrate: int
    # UDS/OBD-II response DBC (CSS Electronics format — decodes polled diagnostic frames)
    uds_dbc: list[Path] = field(default_factory=list)
    # Raw broadcast DBC (reverse-engineered — decodes spontaneous CAN frames)
    raw_dbc: list[Path] = field(default_factory=list)
    # CANedge UDS transmit-list (JSON) — what to poll when logging live
    transmit_list: Optional[Path] = None


def _p(*parts: str) -> Path:
    return Path(*parts)


PROFILES: dict[str, VehicleProfile] = {

    "nissan_leaf": VehicleProfile(
        id="nissan_leaf",
        name="Nissan Leaf (2019, 40/62 kWh)",
        bitrate=500_000,
        uds_dbc=[_DBC_BASE / "can1-nissan-leaf-uds-v2.4.dbc"],
        transmit_list=_TX_BASE / "Nissan-Leaf" / "transmit-list-01.08.json",
    ),

    "hyundai_ioniq5": VehicleProfile(
        id="hyundai_ioniq5",
        name="Hyundai Ioniq 5",
        bitrate=500_000,
        uds_dbc=[_DBC_BASE / "can1-hyundai-kia-uds-v2.4.dbc"],
        transmit_list=_TX_BASE / "Hyundai-Kia" / "transmit-list-01.08.json",
    ),

    "hyundai_kia": VehicleProfile(
        id="hyundai_kia",
        name="Hyundai / Kia (generic)",
        bitrate=500_000,
        uds_dbc=[_DBC_BASE / "can1-hyundai-kia-uds-v2.4.dbc"],
        transmit_list=_TX_BASE / "Hyundai-Kia" / "transmit-list-01.08.json",
    ),

    "skoda_enyaq": VehicleProfile(
        id="skoda_enyaq",
        name="Škoda Enyaq iV (VW MEB)",
        bitrate=500_000,
        uds_dbc=[_DBC_BASE / "can1-vw-skoda-audi-uds-v2.5.dbc"],
        transmit_list=_TX_BASE / "VW-Skoda-Audi" / "transmit-list-01.08.json",
    ),

    "vw_skoda_audi": VehicleProfile(
        id="vw_skoda_audi",
        name="VW / Škoda / Audi (generic MEB/MQB)",
        bitrate=500_000,
        uds_dbc=[_DBC_BASE / "can1-vw-skoda-audi-uds-v2.5.dbc"],
        transmit_list=_TX_BASE / "VW-Skoda-Audi" / "transmit-list-01.08.json",
    ),

    "renault_zoe": VehicleProfile(
        id="renault_zoe",
        name="Renault Zoe",
        bitrate=500_000,
        uds_dbc=[_DBC_BASE / "can1-renault-zoe.dbc"],
    ),

    "tesla_model3": VehicleProfile(
        id="tesla_model3",
        name="Tesla Model 3",
        bitrate=500_000,
        uds_dbc=[_DBC_BASE / "can1-tesla-model-3.dbc"],
        raw_dbc=[_RAW_BASE / "Tesla" / "Model 3" / "tesla-model3-battery-only.log"],  # no raw DBC yet
    ),

    "kia_ev6": VehicleProfile(
        id="kia_ev6",
        name="Kia EV6",
        bitrate=500_000,
        uds_dbc=[_DBC_BASE / "can1-hyundai-kia-uds-v2.4.dbc"],
        raw_dbc=[_RAW_BASE / "Kia EV6" / "Kia-EV6-FD-CAN.dbc"],
    ),

    "bmw_i3": VehicleProfile(
        id="bmw_i3",
        name="BMW i3 (2017, 60Ah REX)",
        bitrate=500_000,
        raw_dbc=[
            _RAW_BASE / "BMW i3" / "BMW-i3-PT-CAN.dbc",
            _RAW_BASE / "BMW i3" / "BMW-i3-PT-CAN2.dbc",
        ],
    ),
}


def get(vehicle_id: str) -> VehicleProfile | None:
    return PROFILES.get(vehicle_id)


def list_all() -> list[dict]:
    return [
        {
            "id":       p.id,
            "name":     p.name,
            "bitrate":  p.bitrate,
            "has_uds_dbc": bool(p.uds_dbc),
            "has_raw_dbc": bool(p.raw_dbc),
            "has_transmit_list": p.transmit_list is not None,
        }
        for p in PROFILES.values()
    ]
