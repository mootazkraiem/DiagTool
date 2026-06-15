#!/usr/bin/env python3
"""
Multi-phase CAN simulation generator.
Produces a realistic replay CSV covering parking / idle / city / highway driving
with 4 injected attack windows: DoS burst, Fuzzy injection, RPM spoofing, Gear spoofing.

Output format: timestamp,can_id,b0,b1,b2,b3,b4,b5,b6,b7,state,attack_type
"""
from __future__ import annotations

import csv
import random
from pathlib import Path

random.seed(42)

OUTPUT = Path(__file__).parent / "simulation.csv"
HEADER = ["timestamp", "can_id", "b0", "b1", "b2", "b3", "b4", "b5", "b6", "b7", "state", "attack_type"]

# Normal traffic CAN IDs (matching training data)
NORMAL_IDS = [260, 316, 329, 545]

rows: list[list] = []


# ── helpers ─────────────────────────────────────────────────────────────────

def _row(t: float, can_id: int, b: list[int], state: str, attack_type: str = "none") -> list:
    return [round(t, 9), can_id, *b[:8], state, attack_type]


def normal_payload(b2: int, b5: int) -> list[int]:
    """Baseline payload matching training-data pattern; b2=RPM indicator, b5=speed indicator."""
    return [0, 128, b2, 51, 0, b5, 5, 0]


def push_cycle(
    t: float,
    b2: int,
    b5: int,
    state: str,
    attack_type: str = "none",
    interval: float = 0.5,
    jitter: float = 0.02,
) -> float:
    """Emit 4 CAN frames (one per normal ID) and return the next cycle start time."""
    for i, can_id in enumerate(NORMAL_IDS):
        rows.append(_row(t + i * 0.020, can_id, normal_payload(b2, b5), state, attack_type))
    return t + interval + random.gauss(0, jitter)


def push_fuzzy_cycle(
    t: float,
    state: str,
    attack_type: str = "Fuzzy",
    interval: float = 0.25,
) -> float:
    """Emit 4 CAN frames with fully random bytes (triggers payload/continuity anomaly)."""
    for i, can_id in enumerate(NORMAL_IDS):
        b = [random.randint(0, 255) for _ in range(8)]
        rows.append(_row(t + i * 0.020, can_id, b, state, attack_type))
    return t + interval + random.gauss(0, 0.005)


def push_dos_flood(t_start: float, duration_s: float, freq_hz: float = 2000.0) -> None:
    """
    Flood CAN IDs 0 and 1 at high frequency with random bytes.
    - Timing layer: freq_anomaly = 1.0 at 2000 Hz  (triggers timing_burst)
    - Payload layer: random bytes → continuity ≈ 1.0 + entropy_like → up to 2.0
    - Combined: fusion_base ≈ 0.35+0.70+0.20×ml → reaches HIGH (0.80+) then CRITICAL (1.0+)
      once entropy_like saturates after ~100 frames (~0.05s at 2000 Hz).
    """
    dt = 1.0 / freq_hz
    t = t_start
    t_end = t_start + duration_s
    while t < t_end:
        rows.append(_row(t,            0, [random.randint(0, 255) for _ in range(8)], "driving", "DoS"))
        rows.append(_row(t + dt * 0.5, 1, [random.randint(0, 255) for _ in range(8)], "driving", "DoS"))
        t += dt


# ═══════════════════════════════════════════════════════════════════════════
# PHASE 1 – PARKING  (t = 0–25 s)
# Engine off. Periodic keep-alive at 1 Hz per-ID. ~100 frames.
# ═══════════════════════════════════════════════════════════════════════════
t = 0.010
while t < 25.0:
    t = push_cycle(t, b2=0, b5=0, state="parking", interval=1.0, jitter=0.05)

# ═══════════════════════════════════════════════════════════════════════════
# PHASE 2 – ENGINE IDLE  (t = 25–55 s)
# Engine started, warming up. RPM ~800 (b2=3), speed=0. ~240 frames.
# ═══════════════════════════════════════════════════════════════════════════
phase_end = t + 30.0
while t < phase_end:
    t = push_cycle(t, b2=3, b5=0, state="idle", interval=0.5, jitter=0.02)

# ═══════════════════════════════════════════════════════════════════════════
# PHASE 3 – CITY DRIVING  (t = 55–85 s)
# Accelerating: b2 (RPM) 0→30, b5 (speed) 0→50. ~480 frames.
# ═══════════════════════════════════════════════════════════════════════════
city_start = t
phase_end = t + 30.0
while t < phase_end:
    p = min(1.0, (t - city_start) / 30.0)
    t = push_cycle(t, b2=int(p * 30), b5=int(p * 50), state="driving", interval=0.25)

# ═══════════════════════════════════════════════════════════════════════════
# PHASE 4 – DoS ATTACK BURST  (t = 85–87 s)
# CAN IDs 0 and 1 flooded at 2000 Hz → triggers timing-layer anomaly.
# Normal background traffic keeps running in parallel. ~4016 frames total.
# ═══════════════════════════════════════════════════════════════════════════
dos_start = t
dos_end = t + 2.0
# background normal frames continue through the window
t_bg = dos_start
while t_bg < dos_end:
    t_bg = push_cycle(t_bg, b2=30, b5=50, state="driving", interval=0.25)
# DoS flood (4000 frames: 2000 per CAN ID)
push_dos_flood(dos_start, duration_s=2.0, freq_hz=2000.0)
t = dos_end

# ═══════════════════════════════════════════════════════════════════════════
# PHASE 5 – RECOVERY  (t = 87–102 s)
# DoS stops, normal city driving resumes. ~240 frames.
# ═══════════════════════════════════════════════════════════════════════════
phase_end = t + 15.0
while t < phase_end:
    t = push_cycle(t, b2=25, b5=40, state="driving", interval=0.25)

# ═══════════════════════════════════════════════════════════════════════════
# PHASE 6 – FUZZY ATTACK  (t = 102–112 s)
# All 8 bytes randomized on normal CAN IDs → triggers payload/continuity anomaly.
# Expected alerts: MEDIUM/HIGH. ~160 frames.
# ═══════════════════════════════════════════════════════════════════════════
phase_end = t + 10.0
while t < phase_end:
    t = push_fuzzy_cycle(t, state="driving", attack_type="Fuzzy", interval=0.25)

# ═══════════════════════════════════════════════════════════════════════════
# PHASE 7 – HIGHWAY DRIVING  (t = 112–142 s)
# Stable high-speed cruise. b2=85 (high RPM), b5=130 (fast). ~480 frames.
# ═══════════════════════════════════════════════════════════════════════════
phase_end = t + 30.0
while t < phase_end:
    t = push_cycle(t, b2=85, b5=130, state="driving", interval=0.25)

# ═══════════════════════════════════════════════════════════════════════════
# PHASE 8 – RPM SPOOFING  (t = 142–152 s)
# b2 cycles through training-matched RPM spoof values; b5 alternates.
# Targets the ML layer (IsolationForest saw this pattern in rpm.csv training).
# Expected alerts: WARNING/MEDIUM. ~160 frames.
# ═══════════════════════════════════════════════════════════════════════════
_rpm_vals = [98, 12, 246, 86, 180, 45, 220, 60, 135, 0]
_rpm_spd  = [66, 66, 89,  66, 89,  66, 89,  66, 89,  80]
rpm_idx = 0
phase_end = t + 10.0
while t < phase_end:
    b2 = _rpm_vals[rpm_idx % len(_rpm_vals)]
    b5 = _rpm_spd [rpm_idx % len(_rpm_spd)]
    rpm_idx += 1
    t = push_cycle(t, b2=b2, b5=b5, state="driving", attack_type="RPM", interval=0.25)

# ═══════════════════════════════════════════════════════════════════════════
# PHASE 9 – RECOVERY  (t = 152–162 s)
# Normal driving after RPM attack. ~160 frames.
# ═══════════════════════════════════════════════════════════════════════════
phase_end = t + 10.0
while t < phase_end:
    t = push_cycle(t, b2=60, b5=100, state="driving", interval=0.25)

# ═══════════════════════════════════════════════════════════════════════════
# PHASE 10 – GEAR SPOOFING  (t = 162–170 s)
# Random bytes matching gear.csv training pattern → IDS flags as payload attack.
# Expected alerts: MEDIUM/HIGH. ~128 frames.
# ═══════════════════════════════════════════════════════════════════════════
phase_end = t + 8.0
while t < phase_end:
    t = push_fuzzy_cycle(t, state="driving", attack_type="Gear", interval=0.25)

# ═══════════════════════════════════════════════════════════════════════════
# PHASE 11 – CITY DRIVING (SLOWING)  (t = 170–185 s)
# Decelerating toward stop: b2 60→0, b5 100→0. ~240 frames.
# ═══════════════════════════════════════════════════════════════════════════
slow_start = t
phase_end = t + 15.0
while t < phase_end:
    p = min(1.0, (t - slow_start) / 15.0)
    b2 = int(60 * (1 - p))
    b5 = int(100 * (1 - p))
    t = push_cycle(t, b2=b2, b5=b5, state="driving", interval=0.25)

# ═══════════════════════════════════════════════════════════════════════════
# PHASE 12 – PARKING  (t = 185–195 s)
# Engine off, vehicle stopped. ~40 frames.
# ═══════════════════════════════════════════════════════════════════════════
phase_end = t + 10.0
while t < phase_end:
    t = push_cycle(t, b2=0, b5=0, state="parking", interval=1.0, jitter=0.05)

# ── sort all rows by timestamp (DoS and background frames interleave) ─────
rows.sort(key=lambda r: r[0])

# ── stats ──────────────────────────────────────────────────────────────────
total = len(rows)
by_attack: dict[str, int] = {}
by_state: dict[str, int] = {}
for r in rows:
    at = r[-1]
    st = r[-2]
    by_attack[at] = by_attack.get(at, 0) + 1
    by_state[st]  = by_state.get(st, 0) + 1

print(f"Total frames : {total}")
print(f"Duration     : {rows[-1][0]:.1f}s")
print("By attack    :", {k: v for k, v in sorted(by_attack.items())})
print("By state     :", {k: v for k, v in sorted(by_state.items())})

# ── write CSV ──────────────────────────────────────────────────────────────
with open(OUTPUT, "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(HEADER)
    writer.writerows(rows)

print(f"\nWritten to   : {OUTPUT}")
