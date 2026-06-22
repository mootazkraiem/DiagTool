from __future__ import annotations

import random


def apply_attack(
    payload: tuple[int, ...],
    attack: str,
    intensity: float,
    frame_idx: int = 0,
    speed_hint: float = 0.0,
) -> tuple[int, ...]:
    if attack == "none":
        return payload
    p = list(payload)
    if attack == "fuzzy":
        return tuple(random.randint(0, 255) for _ in p)
    if attack == "payload_freeze":
        return tuple(payload)
    if attack == "rpm_spoof":
        # Stealthy but unrealistic RPM behavior:
        # periodic impossible spikes + unstable oscillation + torque/accel mismatch
        phase = frame_idx % 80
        osc = int((30 + 70 * intensity) if (phase % 10 < 5) else -(20 + 40 * intensity))
        p[2] = max(0, min(255, p[2] + osc))
        if phase in (8, 9, 10, 11, 40, 41):
            p[2] = min(255, max(p[2], int(210 + 45 * intensity)))
        # torque inconsistency relative to RPM.
        if phase % 16 < 8:
            p[2] = min(255, p[2] + int(15 * intensity))
            p[5] = max(0, p[5] - int(18 * intensity))  # accel dips while RPM rises
        else:
            p[5] = min(255, p[5] + int(12 * intensity))  # accel surges with lower RPM
    elif attack == "gear_spoof":
        # Impossible transmission evolution:
        # rapid flipping and reverse-at-speed signatures.
        phase = frame_idx % 60
        if speed_hint > 25 and phase < 15:
            p[7] = 255  # reverse while moving fast
        elif phase < 30:
            p[7] = 5
        elif phase < 45:
            p[7] = 1
        else:
            p[7] = 4
        # Couple with discontinuous speed/torque hints.
        if phase % 12 < 6:
            p[0] = min(255, p[0] + int(20 * intensity))
            p[2] = max(0, p[2] - int(18 * intensity))
        else:
            p[0] = max(0, p[0] - int(25 * intensity))
            p[2] = min(255, p[2] + int(22 * intensity))
    elif attack == "timing_manipulation":
        p[0] = min(255, int(p[0] + 20 * intensity))
    elif attack == "replay":
        p[1] = p[1]
    elif attack == "DoS":
        p = [255] * 8
    return tuple(p)
