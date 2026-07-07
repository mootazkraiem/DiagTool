from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

try:
    from backend.ml.runtime.ids_statistics import IDSStatistics
    from backend.ml.runtime.realtime_engine import CanFrame, RealtimeEngine
    from backend.offline.session_analyzer import _load_file
except ModuleNotFoundError:
    sys.path.append(str(Path(__file__).resolve().parents[3]))
    from backend.ml.runtime.ids_statistics import IDSStatistics
    from backend.ml.runtime.realtime_engine import CanFrame, RealtimeEngine
    from backend.offline.session_analyzer import _load_file


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--vehicle", type=str, default="", help="Vehicle profile id (e.g. kia_ev6) — selects the matching trained model bundle; falls back to 'general' when omitted")
    p.add_argument("--no-debug", action="store_true", help="Disable debug output for faster processing")
    return p.parse_args()


def main() -> None:
    try:
        args = parse_args()
        print(f"[REPLAY] Loading {args.input} via canonical format-aware loader", file=sys.stderr)
        start_load = time.perf_counter()
        # Reuses backend.offline.session_analyzer's format-aware _load_file() dispatcher
        # (mf4/asc/log/txt/csv) instead of a hardcoded pd.read_csv(). The Log Playback file
        # picker lets users open .log/.asc/.txt/.trc directly (only .mf4 is pre-converted to
        # CSV in C# before replay), and those were previously passed straight to
        # pd.read_csv(), which parses candump/ASC/PCAN text lines as one malformed column,
        # silently producing all-zero timestamps/can_ids/payloads. Sharing the same loader
        # as the offline-analyze path guarantees every replay format enters detection through
        # the identical canonical (timestamp, can_id, payload) stream.
        records = list(_load_file(args.input))
        load_time = time.perf_counter() - start_load
        print(f"[REPLAY] Loaded, rows={len(records)}, load_time={load_time:.2f}s", file=sys.stderr)

        print(f"[REPLAY] Initializing RealtimeEngine (vehicle={args.vehicle or 'general'})", file=sys.stderr)
        engine = RealtimeEngine(vehicle_id=args.vehicle)
        print(f"[REPLAY] RealtimeEngine initialized", file=sys.stderr)

        print(f"[REPLAY] Initializing IDSStatistics", file=sys.stderr)
        stats = IDSStatistics(args.input)
        print(f"[REPLAY] IDSStatistics initialized", file=sys.stderr)

        seen, alerts = 0, 0
        all_alert_records: list[dict] = []
        start_process = time.perf_counter()
        last_progress = start_process

        # Apply limit to records if specified
        if args.limit and args.limit > 0:
            records = records[:args.limit]

        # Pre-allocate arrays for better performance
        timestamps = np.array([r[0] for r in records], dtype=np.float64)
        can_ids = np.array([r[1] for r in records], dtype=np.int32)
        payloads = [r[2] for r in records]
        
        print(f"[REPLAY] Starting processing of {len(records)} frames", file=sys.stderr)
        partial_out = Path("backend/ml/outputs/validation_reports/partial_alerts.json")
        partial_out.parent.mkdir(parents=True, exist_ok=True)

        # Process in batches for better performance
        batch_size = 1000
        for batch_start in range(0, len(records), batch_size):
            batch_end = min(batch_start + batch_size, len(records))
            batch_records = records[batch_start:batch_end]

            for i, _ in enumerate(batch_records):
                global_idx = batch_start + i
                stats.on_frame()
                ts = timestamps[global_idx]
                can_id = can_ids[global_idx]
                payload = payloads[global_idx]
                out = engine.process_frame(CanFrame(timestamp=ts, can_id=can_id, payload=payload))
                stats.on_score(float(out["score"]["fusion_score"]))
                seen += 1

                if out["alert"] is not None:
                    alerts += 1
                    stats.on_alert(out["alert"])
                    if len(all_alert_records) < 1000:
                        all_alert_records.append(out["alert"])

            # Write partial alerts file after every batch (~5 s at 190 fps)
            try:
                partial_out.write_text(
                    json.dumps(all_alert_records, default=str),
                    encoding="utf-8"
                )
            except Exception:
                pass

            # Progress reporting after each batch
            now = time.perf_counter()
            if batch_end % 1000 == 0 or (now - last_progress) > 2.0:
                elapsed = now - start_process
                rate = seen / max(elapsed, 0.001)
                remaining = (len(records) - seen) / max(rate, 0.001)
                print(f"[REPLAY] Progress: {seen}/{len(records)} frames ({rate:.0f} fps, {remaining:.1f}s remaining)", file=sys.stderr)
                last_progress = now
        
        process_time = time.perf_counter() - start_process
        stem = args.input.stem.lower()
        is_normal = "normal" in stem
        stats.print_summary(is_normal=is_normal)
        out_dir = Path("backend/ml/outputs/validation_reports")
        jpath, cpath = stats.save_reports(out_dir, stem=stem, alert_records=all_alert_records)
        print(f"\n[REPLAY] done frames={seen} alerts={alerts} input={args.input}")
        print(f"[REPLAY] processing_time={process_time:.2f}s ({seen/max(process_time, 0.001):.0f} fps)")
        print(f"[REPLAY] summary_json={jpath}")
        print(f"[REPLAY] summary_csv={cpath}")
    except Exception as e:
        print(f"[REPLAY] FATAL ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
