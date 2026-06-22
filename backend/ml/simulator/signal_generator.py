from __future__ import annotations

from backend.ml.simulator.vehicle_state import VehicleState


def signal_snapshot(s: VehicleState) -> dict[str, float]:
    return {
        "speed": s.speed,
        "steering": s.steering,
        "torque": s.torque,
        "brake_pressure": s.brake_pressure,
        "wheel_speed": s.wheel_speed,
        "acceleration": s.acceleration,
        "battery_current": s.battery_current,
        "gear_state": float(s.gear_state),
    }
