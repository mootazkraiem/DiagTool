from __future__ import annotations

from backend.ml.simulator.vehicle_state import VehicleState


def advance_state(s: VehicleState, target_mode: str) -> VehicleState:
    s.mode = target_mode
    if target_mode == "idle":
        s.speed = max(0.0, s.speed - 0.5); s.brake_pressure = 0.2; s.gear_state = 0
    elif target_mode == "parking":
        s.speed = max(0.0, s.speed - 1.0); s.steering *= 0.7; s.gear_state = 0
    elif target_mode == "city_driving":
        s.speed = min(60.0, s.speed + 0.8); s.acceleration = 0.3; s.gear_state = 2
    elif target_mode == "highway":
        s.speed = min(120.0, s.speed + 1.5); s.acceleration = 0.5; s.gear_state = 4
    elif target_mode == "braking":
        s.brake_pressure = min(1.0, s.brake_pressure + 0.1); s.speed = max(0.0, s.speed - 2.0)
    elif target_mode == "reverse":
        s.gear_state = -1; s.speed = min(10.0, s.speed + 0.3)
    s.wheel_speed = s.speed
    s.torque = 0.4 * s.speed
    s.battery_current = 5.0 + 0.3 * s.speed
    return s
