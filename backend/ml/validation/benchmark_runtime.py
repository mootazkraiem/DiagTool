from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd

try:
    from backend.ml.runtime.realtime_engine import CanFrame, RealtimeEngine
except ModuleNotFoundError:
    sys.path.append(str(Path(__file__).resolve().parents[3]))
    from backend.ml.runtime.realtime_engine import CanFrame, RealtimeEngine


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--out", type=Path, default=Path("backend/ml/outputs/validation_reports/runtime_benchmark.json"))
    return p.parse_args()


def main() -> None:
    args = parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(args.input)
    eng = RealtimeEngine()
    t0 = time.perf_counter()
    for _, r in df.iterrows():
        eng.process_frame(CanFrame(float(r["timestamp"]), int(r["can_id"]), tuple(int(r[f"b{i}"]) for i in range(8))))
    elapsed = time.perf_counter() - t0
    fps = len(df) / max(elapsed, 1e-9)
    report = {"frames": int(len(df)), "elapsed_sec": elapsed, "fps": fps, "latency_ms_per_frame": (elapsed / max(len(df), 1)) * 1000.0}
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"[BENCHMARK] {report}")


if __name__ == "__main__":
    main()
