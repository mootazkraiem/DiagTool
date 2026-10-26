"""
signal_discovery.py
───────────────────
Which signals a capture actually carries, found from the capture itself.

With a DBC for the selected vehicle, every frame whose CAN ID the DBC defines is
decoded and the named signals that really vary in this capture are ranked:
speed, state of charge, voltage, current and temperatures first, then the rest
by how much they vary.

Without a DBC nothing can say what a byte means, so nothing is named. The
channels are raw payload bytes - "0x1A1 · byte 2" - leaving out bytes that never
change and rolling counters (a byte that steps by the same amount on nearly
every frame). Smooth channels - small steps compared with their range, as a
physical quantity moves - rank before jumpy ones (checksums, noise), then by how
many distinct values they take. Every raw channel is marked undecoded.

Decoded samples the DBC marks as outside the signal's valid range (typically
"not available" markers such as 0xFFFF) are left out. Rates are measured from
each channel's own samples.

Series are decimated to a fixed number of points across the whole capture, for
display only; min, max and last are taken from every decoded sample.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import Iterable

#: Model ids whose DBC profile has another id.
PROFILE_FOR_MODEL = {"nissan_leaf_2019": "nissan_leaf", "tesla": "tesla_model3"}

#: Importance groups, matched against the lower-cased signal name (first match wins).
PRIORITY = (
    ("speed", ("speed", "velocity")),
    ("soc", ("soc", "stateofcharge", "state_of_charge", "charge_state")),
    ("voltage", ("voltage", "volt")),
    ("current", ("current", "amp")),
    ("temperature", ("temp",)),
)

MAX_DECODED_FRAMES_PER_ID = 5000
MIN_SAMPLES = 3
COUNTER_SHARE = 0.8       # a byte stepping by one constant amount on >= 80% of frames is a counter


@dataclass
class Channel:
    key: str
    label: str
    unit: str
    can_id: int
    decoded: bool
    group: str
    samples: int
    rate_hz: float
    min: float
    max: float
    last: float
    distinct: int
    times: list[float] = field(default_factory=list)
    values: list[float] = field(default_factory=list)


def profile_id(model_id: str) -> str:
    mid = (model_id or "").strip()
    return PROFILE_FOR_MODEL.get(mid, mid)


def _group(name: str) -> tuple[int, str]:
    lowered = name.lower().replace(" ", "")
    for rank, (group, words) in enumerate(PRIORITY):
        if any(w in lowered for w in words):
            return rank, group
    return len(PRIORITY), "other"


def _decimate(times: list[float], values: list[float], points: int) -> tuple[list[float], list[float]]:
    n = len(values)
    if n <= points:
        return times, values
    idx = [round(i * (n - 1) / (points - 1)) for i in range(points)]
    return [times[i] for i in idx], [values[i] for i in idx]


def _rate(times: list[float]) -> float:
    width = times[-1] - times[0] if len(times) > 1 else 0.0
    return (len(times) - 1) / width if width > 0 else 0.0


def _jumpy(values: list[float]) -> bool:
    """True when a channel's typical step is large compared with its range (checksum / noise)."""
    steps = sorted(abs(b - a) for a, b in zip(values, values[1:]) if b != a)
    spread = max(values) - min(values)
    return not steps or spread <= 0 or steps[len(steps) // 2] > 0.25 * spread


def _channel(key, label, unit, can_id, decoded, group, times, values, span, points) -> Channel:
    t, v = _decimate(times, values, points)
    return Channel(key=key, label=label, unit=unit, can_id=can_id, decoded=decoded, group=group,
                   samples=len(values), rate_hz=round(_rate(times), 3),
                   min=float(min(values)), max=float(max(values)), last=float(values[-1]),
                   distinct=len(set(values)), times=[round(x, 4) for x in t], values=[round(x, 4) for x in v])


def _decoded_channels(frames: list[tuple[float, int, tuple]], vehicle: str, t0: float, span: float,
                      points: int) -> list[Channel]:
    from backend.decoding.dbc_manager import get_manager

    mgr = get_manager()
    known = set(mgr.known_can_ids(vehicle))
    if not known:
        return []
    series: dict[tuple[int, str], tuple[str, list[float], list[float]]] = {}
    per_id: dict[int, int] = defaultdict(int)
    for ts, cid, payload in frames:
        if cid not in known or per_id[cid] >= MAX_DECODED_FRAMES_PER_ID:
            continue
        per_id[cid] += 1
        for sig in mgr.decode(vehicle, cid, list(payload)):
            if not isinstance(sig.value, (int, float)) or isinstance(sig.value, bool) or not math.isfinite(float(sig.value)):
                continue
            if sig.out_of_range:
                continue                               # outside the DBC's valid range: a "not available" marker
            entry = series.setdefault((cid, sig.name), (sig.unit, [], []))
            entry[1].append(ts - t0)
            entry[2].append(float(sig.value))

    channels = []
    for (cid, name), (unit, times, values) in series.items():
        if len(values) < MIN_SAMPLES or max(values) == min(values):
            continue                                   # a signal that never changes says nothing here
        _, group = _group(name)
        channels.append(_channel(f"0x{cid:X}:{name}", name, unit, cid, True, group, times, values, span, points))
    channels.sort(key=lambda c: (_group(c.label)[0], _jumpy(c.values), -min(c.distinct, 1000), -c.samples))
    return channels


def _is_counter(values: list[int]) -> bool:
    steps = [(b - a) % 256 for a, b in zip(values, values[1:])]
    if not steps:
        return False
    common = max(set(steps), key=steps.count)
    return common != 0 and steps.count(common) >= COUNTER_SHARE * len(steps)


def _raw_channels(frames: list[tuple[float, int, tuple]], t0: float, span: float, points: int) -> list[Channel]:
    by_id: dict[int, list[tuple[float, tuple]]] = defaultdict(list)
    for ts, cid, payload in frames:
        by_id[cid].append((ts - t0, tuple(payload)))
    channels = []
    for cid, rows in by_id.items():
        times = [r[0] for r in rows]
        for i in range(8):
            values = [int(r[1][i]) if i < len(r[1]) else 0 for r in rows]
            distinct = len(set(values))
            if len(values) < MIN_SAMPLES or distinct < 3 or _is_counter(values):
                continue
            fvalues = [float(v) for v in values]
            ch = _channel(f"0x{cid:X}:b{i}", f"0x{cid:X} · byte {i}", "raw", cid, False, "raw",
                          times, fvalues, span, points)
            channels.append((_jumpy(fvalues), -min(distinct, 64), -ch.rate_hz, ch.key, ch))
    channels.sort(key=lambda item: item[:4])
    return [item[4] for item in channels]


def discover(frames: Iterable[tuple[float, int, tuple]], model_id: str, max_channels: int = 4,
             points: int = 80) -> dict:
    """Ranked signal channels for a capture; see the module docstring."""
    frames = list(frames)
    vehicle = profile_id(model_id)
    if not frames:
        return {"model_id": model_id, "profile": vehicle, "decoder": "none", "dbc_available": False,
                "reason": "the capture contains no frames", "frames": 0, "channels": []}
    t0 = min(f[0] for f in frames)
    span = max(f[0] for f in frames) - t0

    from backend.decoding.dbc_manager import get_manager
    has_dbc = bool(get_manager().known_can_ids(vehicle)) if vehicle else False

    channels = _decoded_channels(frames, vehicle, t0, span, points) if has_dbc else []
    if channels:
        decoder, reason = "dbc", f"decoded with the DBC of profile '{vehicle}'"
    else:
        channels = _raw_channels(frames, t0, span, points)
        decoder = "raw"
        reason = (f"the DBC of profile '{vehicle}' decodes no varying signal in this capture; raw payload bytes shown"
                  if has_dbc else f"no DBC for '{model_id or 'general'}': raw payload bytes shown, not decoded")
    return {"model_id": model_id, "profile": vehicle, "decoder": decoder, "dbc_available": has_dbc,
            "reason": reason, "frames": len(frames), "duration_s": span,
            "channels": [asdict(c) for c in channels[:max_channels]]}
