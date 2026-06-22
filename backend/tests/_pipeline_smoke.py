"""Full ML pipeline end-to-end smoke test (run directly, not via pytest)."""
import time
from pathlib import Path

from backend.data_processing.feature_engineering import FeatureEngineer
from backend.ml.engine import VehicleAIDiagnosticEngine, collect_can_logs_from_assets
from backend.ml import plausibility as plaus
from backend.ml import fingerprint as fp
from backend.ml import alert_grouper as ag

t0 = time.time()

# 1 — seed data
assets_root = Path("assets") / "EV-CANlogs-main"
seed_df, stats = collect_can_logs_from_assets(assets_root)
files_found = stats["files_found"]
rows_parsed = stats["rows_parsed"]
print(f"[1] Seed: {files_found} files, {rows_parsed:,} rows  ({time.time()-t0:.1f}s)")

if seed_df.empty:
    print("No seed data — skipping")
    raise SystemExit(0)

# 2 — feature engineering
t1 = time.time()
featured = FeatureEngineer.build(seed_df)
print(f"[2] Features: {len(featured):,} rows, {len(featured.columns)} cols  ({time.time()-t1:.1f}s)")
for col in ["time_diff", "msg_frequency", "payload_entropy", "inter_arrival_cv"]:
    assert col in featured.columns, f"missing feature: {col}"

# 3 — train
t2 = time.time()
engine = VehicleAIDiagnosticEngine(contamination=0.05)
engine.fit(featured, auto_clusters=True)
assert engine.model_bundle is not None
clusters = engine.model_bundle.n_clusters
print(f"[3] Model: {clusters} clusters  ({time.time()-t2:.1f}s)")

# 4 — predict
t3 = time.time()
predicted = engine.predict(featured)
n_anomaly = (predicted["anomaly"] == -1).sum()
pct = n_anomaly / len(predicted) * 100
print(f"[4] Predict: {n_anomaly:,} anomalies ({pct:.1f}%)  ({time.time()-t3:.1f}s)")
assert 0 < n_anomaly < len(predicted)

# 5 — plausibility on 50 anomalous frames
t4 = time.time()
anomalous = predicted[predicted["anomaly"] == -1].head(50)
checked = violations = 0
for _, row in anomalous.iterrows():
    can_id_hex = f"0x{int(row['can_id']):03X}"
    raw = [int(row.get(f"b{i}", 0)) for i in range(8)]
    result = plaus.check(can_id_hex, raw)
    if result["checked"]:
        checked += 1
        if not result["passed"]:
            violations += 1
print(f"[5] Plausibility: {checked} known IDs, {violations} violations  ({time.time()-t4:.1f}s)")

# 6 — fingerprint (build_baseline + annotate)
t5 = time.time()
fp_sample = featured.head(5000)
baseline = fp.build_baseline(fp_sample)
fp_df = fp.annotate(fp_sample, baseline)
fp_anoms = fp_df["timing_anomaly"].sum() if "timing_anomaly" in fp_df.columns else "N/A"
print(f"[6] Fingerprint: {fp_anoms} timing anomalies, {len(baseline)} baseline IDs  ({time.time()-t5:.1f}s)")

# 7 — alert grouper
t6 = time.time()
contexts = engine.build_anomaly_context(predicted.head(1000))
batch = contexts[:200]
if batch:
    incidents = ag.group(batch)
    print(f"[7] Alert grouper: {len(batch)} alerts -> {len(incidents)} incidents  ({time.time()-t6:.1f}s)")
    if incidents:
        top = incidents[0]
        sev = top["severity"]
        fc = top["frame_count"]
        cid = top["can_id"]
        print(f"    Top: CAN-ID {cid} severity={sev} frames={fc}")
else:
    print("[7] Alert grouper: no contexts")

print()
print(f"FULL ML PIPELINE PASSED  ({time.time()-t0:.1f}s total)")
