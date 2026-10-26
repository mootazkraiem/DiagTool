"""Read-only holdout evaluation + performance/storage review of clean-2-001."""
import contextlib, io, json, sys, time
from pathlib import Path
import numpy as np
from backend.ml.features import canonical
from backend.ml.runtime.model_manifest import SCORED, load_id_family
from backend.ml.training import recordings as rec

V2 = Path("assets/models_staging/clean-2-001")
V1 = json.loads(Path("assets/models_staging/clean-1-001/training_report.json").read_text())["results"]
rep = json.loads((V2 / "training_report.json").read_text())
plan = {r["path"]: r for r in rep["plan"]["recordings"]}
out = {"families": {}}


def load(path):
    r = plan[path]
    with contextlib.redirect_stdout(io.StringIO()):
        f = rec.load_recording(rec.Recording(r["vehicle"], Path("assets") / path, r["fmt"], r["frame_cap"]))
    f = rec.chronological(f)
    x, ready = canonical.compute_features_frame(f)
    return x[ready], f["can_id"].to_numpy(dtype=np.int64)[ready], f


for fam_dir in sorted(p for p in V2.iterdir() if (p / "manifest.json").is_file()):
    fam = fam_dir.name
    t0 = time.perf_counter()
    F = load_id_family(V2, fam)
    load_s = time.perf_counter() - t0
    m = F.manifest
    idm = m["id_models"]
    tr_rows = sum(e["rows"] for e in idm.values())
    tr_flag = sum(e["flagged_count"] for e in idm.values())
    d = {"id_models": len(idm), "sparse_ids": len(m["sparse_ids"]), "unmodelled_ids": len(m["unmodelled_ids"]),
         "training_rows_modelled": tr_rows, "training_flagged": tr_flag,
         "training_flag_rate": tr_flag / tr_rows,
         "training_ids_flag_rate_max": max(e["flagged_count"] / e["rows"] for e in idm.values()),
         "ties_ids": sum(1 for e in idm.values() if e["ties_at_threshold"] > 1),
         "models_file_mb": (fam_dir / "models.joblib").stat().st_size / 1e6,
         "load_seconds": load_s,
         "clean1_holdout": [e.get("share_above_threshold") for e in V1.get(fam, {}).get("holdout_evaluation", [])]}
    hold = [r["path"] for r in m["holdout"]["recordings"]]
    evs = []
    for path in hold:
        x, ids, f = load(path)
        t1 = time.perf_counter()
        norm, flagged, status = F.score_rows(x, ids)
        batch_s = time.perf_counter() - t1
        sc = status == SCORED
        per_id = []
        for cid in np.unique(ids[sc]):
            mk = sc & (ids == cid)
            per_id.append((f"0x{int(cid):X}", int(mk.sum()), float(flagged[mk].mean())))
        per_id.sort(key=lambda t: -t[1] * t[2])
        evs.append({
            "path": path, "frames": int(len(f)), "ready_rows": int(len(ids)),
            "status_share": {s: float((status == s).mean()) for s in sorted(set(status.tolist()))},
            "scored_rows": int(sc.sum()), "flagged": int(flagged.sum()),
            "flagged_share_of_scored": float(flagged[sc].mean()) if sc.any() else None,
            "scored_ids": len(per_id),
            "ids_flagged_over_50pct": sum(1 for _, n, r in per_id if r > 0.5),
            "ids_flagged_100pct": sum(1 for _, n, r in per_id if r == 1.0),
            "top_ids_by_flags": per_id[:6],
            "batch_score_us_per_row": batch_s / max(1, sc.sum()) * 1e6,
            "norm_pct": {q: float(np.nanpercentile(norm[sc], q)) for q in (50, 95, 99)} if sc.any() else {},
        })
    # single-frame latency (live path): score_one on the first modelled ID, 200 calls
    cid = next(iter(F.models))
    vec = [0.5] * len(canonical.FEATURES)
    for i, fname in enumerate(canonical.FEATURES):
        pass
    t2 = time.perf_counter()
    for _ in range(50):
        F.score_one(vec, cid)
    d["score_one_ms"] = (time.perf_counter() - t2) / 50 * 1e3
    d["holdout"] = evs
    out["families"][fam] = d
    print(fam, "done", flush=True)

out["total_models_mb"] = sum(d["models_file_mb"] for d in out["families"].values())
out["total_id_models"] = sum(d["id_models"] for d in out["families"].values())
Path(sys.argv[1]).write_text(json.dumps(out, indent=2), encoding="utf-8")
