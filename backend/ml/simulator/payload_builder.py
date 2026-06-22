from __future__ import annotations


def payload_from_signals(signals: dict[str, float]) -> tuple[int, ...]:
    speed = int(max(0, min(255, round(signals["speed"]))))
    steer = int(max(0, min(255, round(signals["steering"] + 128))))
    torque = int(max(0, min(255, round(signals["torque"]))))
    brake = int(max(0, min(255, round(signals["brake_pressure"] * 255))))
    wheel = int(max(0, min(255, round(signals["wheel_speed"]))))
    accel = int(max(0, min(255, round((signals["acceleration"] + 4) * 20))))
    batt = int(max(0, min(255, round(signals["battery_current"]))))
    gear = int(max(0, min(255, int(signals["gear_state"]) & 0xFF)))
    return (speed, steer, torque, brake, wheel, accel, batt, gear)
