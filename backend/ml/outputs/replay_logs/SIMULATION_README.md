# Mixed-Phase Simulation Dataset

**File:** `simulation.csv`  
**Generator:** `generate_simulation.py` (same directory)  
**Total frames:** 10,468 | **Duration:** ~196 seconds

---

## Purpose

Realistic multi-phase CAN bus replay covering normal vehicle operation (parking → idle → city/highway driving) with four injected attack windows. Designed to exercise all detection layers of the IDS engine simultaneously and produce a mix of LOW / MEDIUM / HIGH / CRITICAL alerts in the analytics dashboard.

---

## CSV Format

```
timestamp, can_id, b0, b1, b2, b3, b4, b5, b6, b7, state, attack_type
```

| Column | Type | Description |
|--------|------|-------------|
| `timestamp` | float (s) | Relative time since replay start |
| `can_id` | int | CAN frame identifier (decimal) |
| `b0–b7` | int 0–255 | 8 payload bytes |
| `state` | string | `parking` / `idle` / `driving` |
| `attack_type` | string | `none` / `DoS` / `Fuzzy` / `RPM` / `Gear` |

**Normal CAN IDs:** 260 (0x104), 316 (0x13C), 329 (0x149), 545 (0x221)  
**DoS flood CAN IDs:** 0 (0x000), 1 (0x001)

---

## Phase Timeline

| Time | Duration | State | Attack | Frames |
|------|----------|-------|--------|--------|
| 0–25 s | 25 s | parking | none | ~100 |
| 25–55 s | 30 s | idle | none | ~240 |
| 55–85 s | 30 s | driving | none | ~480 |
| **85–87 s** | **2 s** | driving | **DoS** | **8,000** |
| 87–102 s | 15 s | driving | none | ~240 |
| **102–112 s** | **10 s** | driving | **Fuzzy** | **164** |
| 112–143 s | 30 s | driving | none | ~480 |
| **143–153 s** | **10 s** | driving | **RPM** | **160** |
| 153–163 s | 10 s | driving | none | ~160 |
| **163–171 s** | **8 s** | driving | **Gear** | **132** |
| 171–186 s | 15 s | driving | none | ~240 |
| 186–196 s | 10 s | parking | none | ~40 |

---

## Attack Signatures

### DoS Burst (85–87 s)
- **CAN IDs:** 0 and 1, alternating every 0.25 ms
- **Rate:** 2,000 Hz per CAN ID → `freq_anomaly = 1.0`
- **Payload:** random bytes each frame (not consistent)
- **Detection layers triggered:**
  - `timing_burst` — frequency exceeds 500 Hz threshold
  - `continuity_break` — random payload with high hamming distance
  - `ml_outlier` — IsolationForest: CAN IDs 0/1 never seen in training
- **Expected severity:** HIGH → CRITICAL
- **Why both timing AND payload:** random bytes ensure continuity ≈ 1.0, so fusion_base = 0.35 × 1.0 (timing) + 0.35 × 1.0+ (payload) + 0.20 × ml ≥ 0.80

### Fuzzy Attack (102–112 s)
- **CAN IDs:** 260, 316, 329, 545 (normal IDs)
- **Rate:** same as normal (~0.25 s cycle)
- **Payload:** all 8 bytes fully randomized each frame
- **Detection layers triggered:**
  - `continuity_break` — high hamming distance between consecutive payloads
  - `can_id_entropy` — CAN ID distribution shifts
- **Expected severity:** LOW → MEDIUM
- **Note:** entropy_like does not fully saturate in a 10 s window (requires ~100 frames per CAN ID); a longer attack produces HIGH

### RPM Spoofing (143–153 s)
- **CAN IDs:** 260, 316, 329, 545
- **Payload:** b2 cycles through spoofed values `[98, 12, 246, 86, 180, 45, 220, 60, 135, 0]`; b5 alternates `[66, 89]` — matching the `rpm.csv` training pattern
- **Detection layers triggered:**
  - ML layer (IsolationForest trained on this pattern from `rpm.csv`)
- **Expected severity:** LOW → MEDIUM

### Gear Spoofing (163–171 s)
- **CAN IDs:** 260, 316, 329, 545
- **Payload:** all 8 bytes randomized (matching `gear.csv` training pattern)
- **Detection layers triggered:**
  - `continuity_break` — same as fuzzy
- **Expected severity:** LOW → MEDIUM

---

## Validated IDS Results

Validated with `replay_runner.py` against `DEFAULT_CONFIG` (alert_threshold=0.40, emit_low_alerts=True):

```
Total alerts      : 78
Max fusion score  : 1.148  (CRITICAL)
Avg fusion score  : 0.823  (HIGH range)

Severity breakdown:
  CRITICAL : 1
  HIGH     : 1
  MEDIUM   : 43
  LOW      : 33

Alert reasons:
  can_id_entropy   : 71
  timing_burst     : 5
  ml_outlier       : 1
  continuity_break : 1
```

---

## How to Use

### Backend replay validation
```bash
python -m backend.ml.runtime.replay_runner \
    --input backend/ml/outputs/replay_logs/simulation.csv
```

### Live UI demo
1. Start the FastAPI backend on port 8765
2. Launch CANvisionNative
3. Navigate to **Log Playback**
4. Select `simulation.csv` from the replay file list
5. Press **Play** — watch the Analytics view for alert spikes at t=85s (DoS), t=102s (Fuzzy), t=143s (RPM), t=163s (Gear)

### Regenerate
```bash
python backend/ml/outputs/replay_logs/generate_simulation.py
```
Edit `generate_simulation.py` to adjust phase durations, attack intensity, or CAN ID assignments.

---

## Normal Traffic Pattern

All 4 normal CAN IDs share the same base payload structure:

| Byte | Normal value | Role |
|------|-------------|------|
| b0 | 0 | flags / throttle indicator |
| b1 | 128 | constant reference field |
| b2 | varies | RPM indicator (0 = stopped, 85 = highway cruise) |
| b3 | 51 | constant |
| b4 | 0 | constant |
| b5 | varies | speed indicator (0 = stopped, 130 = highway) |
| b6 | 5 | constant |
| b7 | 0 | constant |

b2 and b5 ramp linearly during acceleration/deceleration phases, producing gradual payload changes that the IDS correctly classifies as normal.
