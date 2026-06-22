from __future__ import annotations

from dataclasses import dataclass


@dataclass
class VehicleState:
    mode: str = "idle"
    speed: float = 0.0
    steering: float = 0.0
    torque: float = 0.0
    brake_pressure: float = 0.0
    wheel_speed: float = 0.0
    acceleration: float = 0.0
    battery_current: float = 0.0
    gear_state: int = 0
