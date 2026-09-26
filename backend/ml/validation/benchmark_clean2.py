"""Throughput and latency of the clean-2 live path, per promoted family.

Runs the loop backend/ml/runtime/replay_runner.py runs - one RealtimeEngine for the
selected vehicle (built by model_status.live_engine, as live hardware does), one
process_frame call per frame - over the first N frames of a holdout recording, and
times every frame and every per-CAN-ID model call. Nothing is optimised or changed;
this measures what the production path costs.

    python -m backend.ml.validation.benchmark_clean2 --frames 30000 --out report.json
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import time
from pathlib import Path

import numpy as np

from backend.ml.runtime.model_status import live_engine
from backend.ml.runtime.realtime_engine import CanFrame
from backend.ml.training import recordings as rec

ASSETS = Path(__file__).resolve().parents[3] / "assets"

#: Holdout recording of each promoted family (clean-2-002 split), and its format.
RECORDINGS = {
    "kia_ev6": ("EV-CANlogs-main/Kia EV6/Vehicle everthing on.asc", "vector_asc"),
    "road_ambient": ("road/road/ambient/ambient_highway_street_driving_long.log", "candump_ts"),
    "nissan_leaf_2019": ("Train/Nissan Leaf 2019/LOG/2F6913DB/00000021/00000001-61D9D9BA.MF4", "mf4"),
    "jaguar_ipace": ("EV-CANlogs-main/Jaguar IPACE/canbus_turningon_quickly.csv", "savvycan_csv"),
}


def _pct(values: np.ndarray) -> dict:
    return {"mean": float(values.mean()), "p50": float(np.median(values)),
            "p99": float(np.percentile(values, 99)), "max": float(values.max())}


def benchmark(family: str, frames: int) -> dict:
    path, fmt = RECORDINGS[family]
    with contextlib.redirect_stdout(io.StringIO()):
        f = rec.chronological(rec.load_recording(rec.Recording(family, ASSETS / path, fmt, frames)))
        engine = live_engine(family)
    fam = engine._family
    model_ms: list[float] = []
    original = fam.score_one

    def timed(vec, can_id):
        t = time.perf_counter()
        result = original(vec, can_id)
        model_ms.append((time.perf_counter() - t) * 1e3)
        return result

    fam.score_one = timed
    frame_ms, states, alerts = [], {}, 0
    ts, ids = f["timestamp"].to_numpy(), f["can_id"].to_numpy()
    payloads = f[[f"b{i}" for i in range(8)]].to_numpy().tolist()
    start = time.perf_counter()
    with contextlib.redirect_stdout(io.StringIO()):
        for t, c, p in zip(ts, ids, payloads):
            t0 = time.perf_counter()
            out = engine.process_frame(CanFrame(timestamp=float(t), can_id=int(c), payload=tuple(p)))
            frame_ms.append((time.perf_counter() - t0) * 1e3)
            states[out["vehicle_state"]] = states.get(out["vehicle_state"], 0) + 1
            alerts += out["alert"] is not None
    wall = time.perf_counter() - start
    span = float(ts[-1] - ts[0]) or 1e-9
    return {
        "family": family, "model_version": fam.manifest["model_version"], "frames": int(len(f)),
        "bus_frames_per_s": len(f) / span, "processed_frames_per_s": len(f) / wall,
        "realtime_factor": span / wall, "vehicle_states": states,
        "model_calls": len(model_ms), "model_call_ms": _pct(np.array(model_ms or [0.0])),
        "process_frame_ms": _pct(np.array(frame_ms)), "alerts": alerts, "alerts_per_bus_s": alerts / span,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=30000)
    ap.add_argument("--family", action="append", choices=sorted(RECORDINGS))
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    results = [benchmark(fam, args.frames) for fam in (args.family or sorted(RECORDINGS))]
    args.out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    for r in results:
        print(f"{r['family']:<18} bus {r['bus_frames_per_s']:8.0f} fps  processed {r['processed_frames_per_s']:6.0f} fps  "
              f"x{r['realtime_factor']:.2f}  model call {r['model_call_ms']['mean']:.1f} ms (p99 {r['model_call_ms']['p99']:.1f})")


if __name__ == "__main__":
    main()
