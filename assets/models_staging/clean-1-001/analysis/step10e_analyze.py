"""STEP 10E: read-only holdout analysis of assets/models_staging/clean-1-001.

Loads each staged family through the validating loader, rebuilds the training
and holdout canonical features exactly as training did (per recording, time
order, warm-up rows dropped), and compares them. Writes only the JSON data file
given on the command line.
"""
import contextlib
import io
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from backend.ml.features import canonical
from backend.ml.runtime.model_manifest import load_family_model
from backend.ml.training import recordings as rec

ROOT = Path("assets/models_staging/clean-1-001")
ASSETS = Path("assets")
OUT = Path(sys.argv[1])
TRAIN_SCORE_CAP = 400_000          # training rows scored: every k-th row, deterministic
FEATS = list(canonical.FEATURES)
t0 = time.time()


def log(m):
    print(f"[{time.time()-t0:6.0f}s] {m}", flush=True)


report = json.loads((ROOT / "training_report.json").read_text())
plan_recs = {r["path"]: r for r in report["plan"]["recordings"]}


def load(path):
    r = plan_recs[path]
    with contextlib.redirect_stdout(io.StringIO()):
        f = rec.load_recording(rec.Recording(r["vehicle"], ASSETS / path, r["fmt"], r["frame_cap"]))
    return rec.chronological(f)


def recording_meta(path, f):
    ts = f["timestamp"].to_numpy()
    dt = np.diff(ts)
    pos = dt[dt > 0]
    return {"path": path, "fmt": plan_recs[path]["fmt"], "frames": int(len(f)),
            "duration_s": float(ts[-1] - ts[0]), "fps": float((len(f) - 1) / max(ts[-1] - ts[0], 1e-9)),
            "can_ids": int(f["can_id"].nunique()),
            "min_positive_step_s": float(pos.min()) if len(pos) else None,
            "share_steps_zero": float((dt == 0).mean()),
            "share_steps_whole_ms": float(np.isclose(pos * 1000, np.round(pos * 1000), atol=1e-6).mean()) if len(pos) else None}


def features(f):
    x, ready = canonical.compute_features_frame(f)
    return x[ready], f["can_id"].to_numpy()[ready]


def pct(a, qs=(1, 5, 25, 50, 75, 95, 99)):
    return {f"p{q}": float(np.percentile(a, q)) for q in qs} if len(a) else {}


def ks(a, b):
    a, b = np.sort(a), np.sort(b)
    grid = np.concatenate([a, b])
    return float(np.max(np.abs(np.searchsorted(a, grid, "right") / len(a) - np.searchsorted(b, grid, "right") / len(b))))


def per_id_timing(f):
    out = {}
    for cid, g in f.groupby("can_id"):
        d = np.diff(g["timestamp"].to_numpy())
        out[int(cid)] = {"frames": int(len(g)), "median_period_ms": float(np.median(d) * 1000) if len(d) else None}
    return out


results = {}
for fam in sorted(p.name for p in ROOT.iterdir() if (p / "manifest.json").is_file()):
    m = load_family_model(ROOT, fam)
    hold_paths = [r["path"] for r in m.manifest["holdout"]["recordings"]]
    if not hold_paths:
        continue
    train_paths = [r["path"] for r in m.manifest["training_corpus"]["recordings"]]
    log(f"{fam}: {len(train_paths)} train, {len(hold_paths)} holdout")
    idx = m.feature_index

    def score(x):
        z = m.scaler.transform(x[:, idx])
        raw = m.model.decision_function(z)
        span = max(abs(m.threshold), 0.01)
        return raw, np.clip(0.5 + (m.threshold - raw) / (2 * span), 0, 1)

    tr_x, tr_id, tr_src, tr_meta, tr_timing = [], [], [], [], {}
    for p in train_paths:
        f = load(p)
        tr_meta.append(recording_meta(p, f))
        for cid, v in per_id_timing(f).items():
            tr_timing.setdefault(cid, []).append(v)
        x, ids = features(f)
        tr_x.append(x); tr_id.append(ids); tr_src.append(np.full(len(x), len(tr_meta) - 1))
    tr_x = np.vstack(tr_x); tr_id = np.concatenate(tr_id); tr_src = np.concatenate(tr_src)

    ho_meta = []
    ho_x, ho_id, ho_timing = [], [], {}
    for p in hold_paths:
        f = load(p)
        ho_meta.append(recording_meta(p, f))
        for cid, v in per_id_timing(f).items():
            ho_timing[cid] = v
        x, ids = features(f)
        ho_x.append(x); ho_id.append(ids)
    ho_x = np.vstack(ho_x); ho_id = np.concatenate(ho_id)

    stride = max(1, len(tr_x) // TRAIN_SCORE_CAP)
    tr_raw, tr_s = score(tr_x[::stride])
    ho_raw, ho_s = score(ho_x)
    flagged = ho_s >= 0.5

    # per-feature comparison (all canonical features; model-used ones marked)
    feat_cmp = {}
    lo, hi = np.percentile(tr_x, 0.5, axis=0), np.percentile(tr_x, 99.5, axis=0)
    tr_med = np.median(tr_x, axis=0)
    for j, name in enumerate(FEATS):
        a, b = tr_x[::stride, j], ho_x[:, j]
        outside = (ho_x[:, j] < lo[j]) | (ho_x[:, j] > hi[j])
        feat_cmp[name] = {"used": name in m.features, "train": pct(a, (5, 25, 50, 75, 95)),
                          "holdout": pct(b, (5, 25, 50, 75, 95)), "ks": ks(a, b),
                          "holdout_outside_train_p0.5_p99.5": float(outside.mean()),
                          "flagged_outside_train_p0.5_p99.5": float(outside[flagged].mean()) if flagged.any() else None}

    # ablation: set one feature of the flagged rows to its training median; share that drops below threshold
    ablation = {}
    if flagged.any():
        fx = ho_x[flagged]
        for name in m.features:
            j = FEATS.index(name)
            y = fx.copy(); y[:, j] = tr_med[j]
            _, s2 = score(y)
            ablation[name] = float((s2 < 0.5).mean())

    # per CAN ID
    ids = np.unique(ho_id)
    tr_counts = pd.Series(tr_id).value_counts()
    per_id = []
    for cid in ids:
        mask = ho_id == cid
        per_id.append({"can_id": f"0x{int(cid):X}", "holdout_rows": int(mask.sum()),
                       "flagged": int(flagged[mask].sum()), "flag_rate": float(flagged[mask].mean()),
                       "train_rows": int(tr_counts.get(cid, 0)),
                       "train_median_period_ms": [t["median_period_ms"] for t in tr_timing.get(int(cid), [])],
                       "holdout_median_period_ms": ho_timing.get(int(cid), {}).get("median_period_ms")})
    per_id.sort(key=lambda r: -r["flagged"])
    unseen = [r for r in per_id if r["train_rows"] == 0]

    tr_ids, ho_ids = set(np.unique(tr_id).tolist()), set(ids.tolist())
    results[fam] = {
        "features": m.features, "threshold": m.threshold,
        "train_recordings": tr_meta, "holdout_recordings": ho_meta,
        "holdout_rows": int(len(ho_x)), "holdout_flagged": int(flagged.sum()),
        "holdout_flag_rate": float(flagged.mean()),
        "train_rows": int(len(tr_x)), "train_rows_scored": int(len(tr_s)), "train_score_stride": stride,
        "train_flag_rate": float((tr_s >= 0.5).mean()),
        "train_score_pct": pct(tr_s), "holdout_score_pct": pct(ho_s),
        "train_decision_pct": pct(tr_raw), "holdout_decision_pct": pct(ho_raw),
        "can_ids": {"train": len(tr_ids), "holdout": len(ho_ids), "shared": len(tr_ids & ho_ids),
                    "holdout_only": sorted(f"0x{c:X}" for c in ho_ids - tr_ids),
                    "train_only_count": len(tr_ids - ho_ids)},
        "holdout_rows_on_unseen_ids": int(sum(r["holdout_rows"] for r in unseen)),
        "flagged_on_unseen_ids": int(sum(r["flagged"] for r in unseen)),
        "top_flagged_ids": per_id[:10],
        "top10_share_of_flags": float(sum(r["flagged"] for r in per_id[:10]) / max(1, flagged.sum())),
        "per_id": per_id,
        "feature_comparison": feat_cmp,
        "ablation_unflag_share": ablation,
    }
    log(f"  holdout flag {flagged.mean()*100:.2f}%  train flag {(tr_s>=0.5).mean()*100:.2f}%")

OUT.write_text(json.dumps(results, indent=2), encoding="utf-8")
log("DONE")
