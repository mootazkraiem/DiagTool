"""Read-only validation of clean-2-002 and comparison with clean-2-001."""
import contextlib, io, json, math, sys, time
from pathlib import Path
import numpy as np
from backend.ml.features import canonical
from backend.ml.runtime.model_manifest import SCORED, UNSEEN_ID, load_id_family
from backend.ml.training import recordings as rec
from backend.ml.training.model_promotion import validate_staging

STG = Path("assets/models_staging")
out = {}


def load(plan, path):
    r = plan[path]
    with contextlib.redirect_stdout(io.StringIO()):
        f = rec.load_recording(rec.Recording(r["vehicle"], Path("assets") / path, r["fmt"], r["frame_cap"]))
    f = rec.chronological(f)
    x, ready = canonical.compute_features_frame(f)
    return x[ready], f["can_id"].to_numpy(dtype=np.int64)[ready], f["can_id"].to_numpy(dtype=np.int64)


checks = {}
for ver in ("clean-2-001", "clean-2-002"):
    root = STG / ver
    fams = validate_staging(root)
    plan = {r["path"]: r for r in json.loads((root / "training_report.json").read_text())["plan"]["recordings"]}
    out[ver] = {}
    for name, F in sorted(fams.items()):
        m = F.manifest
        idm = m["id_models"]
        d = {"id_models": len(idm), "sparse_ids": len(m["sparse_ids"]),
             "sparse_rows0": sum(1 for e in m["sparse_ids"].values() if e["rows"] == 0),
             "validation": (m.get("validation") or {}).get("status", "(not recorded)"),
             "training_rows_modelled": sum(e["rows"] for e in idm.values()),
             "training_flagged": sum(e["flagged_count"] for e in idm.values()),
             "models_mb": (root / name / "models.joblib").stat().st_size / 1e6}
        d["training_flag_rate"] = d["training_flagged"] / d["training_rows_modelled"]
        tr_paths = [r["path"] for r in m["training_corpus"]["recordings"]]
        ho_paths = [r["path"] for r in m["holdout"]["recordings"]]
        d["leakage"] = sorted(set(tr_paths) & set(ho_paths))
        if ver == "clean-2-002":
            # label check: every training ID is listed; nothing seen is unseen at runtime
            parts = [load(plan, p) for p in tr_paths]
            seen = set(np.concatenate([p[2] for p in parts]).tolist())
            listed = {int(k, 16) for k in list(idm) + list(m["sparse_ids"]) + list(m["unmodelled_ids"])}
            d["training_ids"] = len(seen)
            d["training_ids_unlisted"] = len(seen - listed)
            d["listed_not_in_training"] = len(listed - seen)
            d["seen_ids_reported_unseen"] = sum(1 for c in seen if F.status(c) == UNSEEN_ID)
            # calibration: recompute each ID's scores on its training rows
            x = np.vstack([p[0] for p in parts]); ids = np.concatenate([p[1] for p in parts])
            bad = []
            for key, e in idm.items():
                cid = int(key, 16)
                mdl = F.models[cid]
                raw = mdl.model.score_samples(x[ids == cid][:, mdl.feature_index])
                k = math.floor(m["calibration"]["target_contamination"] * len(raw))
                ok = (len(raw) == e["rows"] and k == e["k"] and float(np.sort(raw)[k]) == e["threshold"]
                      and int((raw < e["threshold"]).sum()) == e["flagged_count"]
                      and int((raw == e["threshold"]).sum()) == e["ties_at_threshold"]
                      and float(np.median(raw)) == e["median"])
                if not ok:
                    bad.append(key)
            d["calibration_recomputed_ids"] = len(idm)
            d["calibration_mismatches"] = bad
        ev = []
        for p in ho_paths:
            xh, idh, _ = load(plan, p)
            _, flagged, status = F.score_rows(xh, idh)
            sc = status == SCORED
            ev.append({"path": p, "rows": int(len(idh)),
                       "status_share": {s: float((status == s).mean()) for s in sorted(set(status.tolist()))},
                       "flagged": int(flagged.sum()), "scored": int(sc.sum()),
                       "flagged_share_of_scored": float(flagged[sc].mean()) if sc.any() else None})
        d["holdout"] = ev
        out[ver][name] = d
        print(ver, name, "done", flush=True)

Path(sys.argv[1]).write_text(json.dumps(out, indent=2), encoding="utf-8")
