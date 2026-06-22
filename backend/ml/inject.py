"""Attack injection module.

Generates synthetic CAN attack frames and injects them into an existing
DataFrame so the full ML + plausibility + fingerprint pipeline can be
validated end-to-end without real hardware.

Supported attack types
----------------------
dos         — flood a target CAN ID at N× its normal frequency
fuzzy       — random CAN IDs with random payloads
rpm_spoof   — replace EMS11 (0x316) N signal with extreme RPM values
gear_inject — replace EMS12 (0x329) GP_CTL/TPS with invalid gear state
"""
from __future__ import annotations

import random
from typing import Any

import numpy as np
import pandas as pd


# ── Hyundai EMS CAN IDs (decimal) ─────────────────────────────────────────────
_EMS11_DEC = 790   # 0x316 — Engine RPM (N signal bytes 2-3, LE, ×0.25)
_EMS12_DEC = 809   # 0x329 — Instrument cluster / gear state

_ATTACK_TYPES = {"dos", "fuzzy", "rpm_spoof", "gear_inject"}


def _normal_ifi(df: pd.DataFrame, can_id_dec: int) -> float:
    """Compute mean inter-frame interval for a CAN ID in seconds."""
    rows = df[df["can_id"] == can_id_dec].sort_values("timestamp")
    if len(rows) < 2:
        return 0.01
    return float(np.diff(rows["timestamp"].values).mean())


def _byte_cols(df: pd.DataFrame) -> list[str]:
    return [c for c in ["b0", "b1", "b2", "b3", "b4", "b5", "b6", "b7"] if c in df.columns]


def generate(
    base_df: pd.DataFrame,
    attack_type: str,
    intensity: float = 0.5,
    duration_sec: float = 5.0,
    target_can_id: int | None = None,
    seed: int = 42,
) -> pd.DataFrame:
    """
    Inject synthetic attack frames into base_df.

    Args:
        base_df:        Original CAN log DataFrame.
        attack_type:    One of 'dos', 'fuzzy', 'rpm_spoof', 'gear_inject'.
        intensity:      0.0–1.0, controls severity (frame count / payload extremity).
        duration_sec:   How long the attack window lasts (seconds into the log).
        target_can_id:  For DoS/spoof: which CAN ID to attack.
        seed:           Random seed for reproducibility.

    Returns:
        New DataFrame = base_df + injected frames, sorted by timestamp.
        Each injected frame has 'injected=True' and 'attack_label' columns.
    """
    if attack_type not in _ATTACK_TYPES:
        raise ValueError(f"Unknown attack_type '{attack_type}'. Use: {_ATTACK_TYPES}")

    rng = random.Random(seed)
    np_rng = np.random.default_rng(seed)

    b_cols = _byte_cols(base_df)
    if not b_cols:
        b_cols = ["b0", "b1", "b2", "b3", "b4", "b5", "b6", "b7"]

    # Injection window: last `duration_sec` seconds of the log
    if "timestamp" in base_df.columns and not base_df.empty:
        t_end = float(base_df["timestamp"].max())
        t_start = max(float(base_df["timestamp"].min()), t_end - duration_sec)
    else:
        t_start, t_end = 0.0, duration_sec

    injected_rows: list[dict] = []

    # ── DoS flood ─────────────────────────────────────────────────────────────
    if attack_type == "dos":
        target = target_can_id if target_can_id is not None else _EMS11_DEC
        normal_ifi = _normal_ifi(base_df, target)
        # Flood at (1 + intensity * 9)× normal rate → 1× to 10× normal
        attack_ifi = normal_ifi / max(1.0, 1.0 + intensity * 9.0)
        ts = t_start
        while ts <= t_end:
            row = {
                "timestamp": ts,
                "can_id": target,
                "injected": True,
                "attack_label": "dos_flood",
            }
            for b in b_cols:
                row[b] = rng.randint(0, 255)
            injected_rows.append(row)
            ts += attack_ifi

    # ── Fuzzy attack ──────────────────────────────────────────────────────────
    elif attack_type == "fuzzy":
        n_frames = int(200 + intensity * 800)
        timestamps = np_rng.uniform(t_start, t_end, n_frames)
        for ts in sorted(timestamps):
            random_id = rng.randint(0, 0x7FF)
            row = {
                "timestamp": float(ts),
                "can_id": random_id,
                "injected": True,
                "attack_label": "fuzzy_payload",
            }
            for b in b_cols:
                row[b] = rng.randint(0, 255)
            injected_rows.append(row)

    # ── RPM spoof ─────────────────────────────────────────────────────────────
    elif attack_type == "rpm_spoof":
        target = target_can_id if target_can_id is not None else _EMS11_DEC
        normal_ifi = _normal_ifi(base_df, target)
        # RPM = N signal: bytes 2-3 LE, scale 0.25 → 16383.75 rpm max
        # Spoof to: 10000 + intensity*6000 rpm
        spoof_rpm = 10000 + intensity * 6000
        # raw_val = rpm / 0.25
        raw_val = min(0xFFFF, int(spoof_rpm / 0.25))
        b2 = raw_val & 0xFF
        b3 = (raw_val >> 8) & 0xFF
        ts = t_start
        while ts <= t_end:
            row = {
                "timestamp": ts,
                "can_id": target,
                "injected": True,
                "attack_label": "rpm_spoof",
                "b0": rng.randint(0, 255),
                "b1": rng.randint(0, 255),
                "b2": b2,
                "b3": b3,
                "b4": rng.randint(0, 255),
                "b5": rng.randint(0, 255),
                "b6": rng.randint(0, 255),
                "b7": rng.randint(0, 255),
            }
            for b in b_cols:
                if b not in row:
                    row[b] = 0
            injected_rows.append(row)
            ts += normal_ifi

    # ── Gear injection ────────────────────────────────────────────────────────
    elif attack_type == "gear_inject":
        target = target_can_id if target_can_id is not None else _EMS12_DEC
        normal_ifi = _normal_ifi(base_df, target)
        # EMS12 byte 5 = PV_AV_CAN (accelerator %), set to 100% = 0xFF
        # byte 4 = TPS (throttle %) , set to 100%
        ts = t_start
        while ts <= t_end:
            row = {
                "timestamp": ts,
                "can_id": target,
                "injected": True,
                "attack_label": "gear_state_injection",
                "b0": rng.randint(0, 255),
                "b1": 0xFF,   # TorqueRequest max
                "b2": rng.randint(0, 255),
                "b3": 0xFF,   # BRAKE_ACT flags all set
                "b4": 0xFF,   # TPS 100%
                "b5": 0xFF,   # PV_AV_CAN 100%
                "b6": rng.randint(0, 255),
                "b7": rng.randint(0, 255),
            }
            for b in b_cols:
                if b not in row:
                    row[b] = 0
            injected_rows.append(row)
            ts += normal_ifi

    if not injected_rows:
        return base_df.copy()

    inject_df = pd.DataFrame(injected_rows)

    # Ensure base_df has the injected/attack_label columns too
    out = base_df.copy()
    if "injected" not in out.columns:
        out["injected"] = False
    if "attack_label" not in out.columns:
        out["attack_label"] = "normal"

    result = pd.concat([out, inject_df], ignore_index=True)
    if "timestamp" in result.columns:
        result = result.sort_values("timestamp").reset_index(drop=True)

    return result


def summary(injected_df: pd.DataFrame) -> dict[str, Any]:
    """Return a quick summary of the injection."""
    if "injected" not in injected_df.columns:
        return {"injected_frames": 0}

    inj = injected_df[injected_df["injected"] == True]  # noqa: E712
    by_type: dict[str, int] = {}
    if "attack_label" in inj.columns:
        for label, grp in inj.groupby("attack_label"):
            by_type[str(label)] = len(grp)

    return {
        "total_frames": len(injected_df),
        "injected_frames": len(inj),
        "normal_frames": len(injected_df) - len(inj),
        "injection_rate_pct": round(100 * len(inj) / max(len(injected_df), 1), 2),
        "by_attack_type": by_type,
    }
