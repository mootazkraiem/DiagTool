from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
from collections import Counter

try:
    from backend.ml.simulator.attack_generator import apply_attack
    from backend.ml.simulator.payload_builder import payload_from_signals
    from backend.ml.simulator.signal_generator import signal_snapshot
    from backend.ml.simulator.state_machine import advance_state
    from backend.ml.simulator.timing_generator import next_timestamp
    from backend.ml.simulator.vehicle_state import VehicleState
except ModuleNotFoundError:
    sys.path.append(str(Path(__file__).resolve().parents[3]))
    from backend.ml.simulator.attack_generator import apply_attack
    from backend.ml.simulator.payload_builder import payload_from_signals
    from backend.ml.simulator.signal_generator import signal_snapshot
    from backend.ml.simulator.state_machine import advance_state
    from backend.ml.simulator.timing_generator import next_timestamp
    from backend.ml.simulator.vehicle_state import VehicleState


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--frames", type=int, default=5000)
    p.add_argument("--attack", type=str, default="none")
    p.add_argument("--intensity", type=float, default=0.5)
    p.add_argument("--out", type=Path, default=Path("backend/ml/outputs/replay_logs/simulated_traffic.csv"))
    return p.parse_args()


def normalize_attack_name(name: str) -> tuple[str, str]:
    attack_lc = str(name).strip().lower()
    mapping = {
        "none": ("none", "none"),
        "fuzzy": ("fuzzy", "fuzzy"),
        "dos": ("DoS", "dos"),
        "replay": ("replay", "replay"),
        "rpm": ("rpm_spoof", "rpm"),
        "rpm_spoof": ("rpm_spoof", "rpm"),
        "gear": ("gear_spoof", "gear"),
        "gear_spoof": ("gear_spoof", "gear"),
        "payload_freeze": ("payload_freeze", "payload_freeze"),
        "timing_manipulation": ("timing_manipulation", "timing_manipulation"),
    }
    return mapping.get(attack_lc, (attack_lc, attack_lc))


def main() -> None:
    args = parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    modes = ["idle", "parking", "city_driving", "highway", "braking", "reverse"]
    s = VehicleState()
    ts = 0.0
    rows = []
    base_ids = [0x104, 0x13C, 0x149, 0x221]
    attack_logic, attack_label = normalize_attack_name(args.attack)
    # Hard guard against accidental cross-mapping during CLI usage.
    if str(args.attack).strip().lower() == "rpm" and attack_label != "rpm":
        raise ValueError(f"Attack mapping error: rpm resolved to {attack_label}")
    if str(args.attack).strip().lower() == "gear" and attack_label != "gear":
        raise ValueError(f"Attack mapping error: gear resolved to {attack_label}")
    print(f"[SIM] attack arg={args.attack} -> logic={attack_logic}, label={attack_label}")
    dos_mode = attack_logic.lower() == "dos"
    dos_ids = [0x000, 0x001]
    dos_spacing = max(0.00005, 0.0006 * (1.0 - min(max(args.intensity, 0.0), 1.0)))
    dos_burst_gap = 0.025
    dos_burst_len = max(20, int(220 * max(args.intensity, 0.1)))
    dos_cycle = dos_burst_len + 120

    frames_modified = 0
    attack_ids: Counter[int] = Counter()

    for i in range(args.frames):
        mode = modes[(i // 800) % len(modes)]
        s = advance_state(s, mode)
        sig = signal_snapshot(s)
        payload_base = payload_from_signals(sig)
        payload = payload_base
        payload = apply_attack(
            payload,
            attack_logic,
            args.intensity,
            frame_idx=i,
            speed_hint=float(sig.get("speed", 0.0)),
        )
        if payload != payload_base:
            frames_modified += 1

        if dos_mode:
            in_burst = (i % dos_cycle) < dos_burst_len
            if in_burst:
                # Flood with near-zero spacing and dominant arbitration IDs.
                ts = ts + dos_spacing
                can_id = dos_ids[i % len(dos_ids)]
            else:
                # Return briefly to normal cadence between attack pulses.
                ts = next_timestamp(ts, i % 4)
                can_id = base_ids[i % len(base_ids)]
                if i % dos_cycle == dos_burst_len:
                    ts = ts + dos_burst_gap
        else:
            ts = next_timestamp(ts, i % 4)
            can_id = base_ids[i % len(base_ids)]
        if attack_label != "none":
            attack_ids[can_id] += 1

        rows.append({"timestamp": ts, "can_id": can_id, **{f"b{k}": payload[k] for k in range(8)}, "state": mode, "attack_type": attack_label})

    pd.DataFrame(rows).to_csv(args.out, index=False)
    print(f"[SIM] wrote {len(rows)} frames to {args.out}")
    labeled_rows = sum(1 for r in rows if str(r.get("attack_type", "")).lower() not in ("", "none"))
    print("[SIM SUMMARY]")
    print(f"Attack type: {attack_label}")
    print(f"Frames modified: {frames_modified}")
    if attack_ids:
        top_ids = ", ".join([f"0x{k:03X}:{v}" for k, v in attack_ids.most_common(4)])
    else:
        top_ids = "none"
    print(f"Attack CAN IDs: {top_ids}")
    print(f"Rows exported with attack labels: {labeled_rows}")
    if dos_mode and len(rows) > 2:
        ts_series = pd.Series([r["timestamp"] for r in rows], dtype=float)
        delta = ts_series.diff().dropna()
        id_counts = Counter(int(r["can_id"]) for r in rows)
        dominant_id, dominant_count = id_counts.most_common(1)[0]
        burst_density = float((delta <= (dos_spacing * 1.5)).mean())
        print("[DoS STATS]")
        print(f"avg inter-arrival: {float(delta.mean()):.6f}s")
        print(f"min inter-arrival: {float(delta.min()):.6f}s")
        print(f"dominant CAN ID frequency: 0x{dominant_id:03X} -> {dominant_count}/{len(rows)}")
        print(f"burst density: {burst_density:.3f}")


if __name__ == "__main__":
    main()
