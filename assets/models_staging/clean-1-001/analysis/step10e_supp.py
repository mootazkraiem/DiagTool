"""STEP 10E supplement (read-only): per-CAN-ID training flag rates, flag rate vs ID
volume, per-source flag rates, and the decision-score shape behind the threshold."""
import contextlib, io, json, sys
from pathlib import Path
import numpy as np
import pandas as pd
from backend.ml.features import canonical
from backend.ml.runtime.model_manifest import load_family_model
from backend.ml.training import recordings as rec

ROOT = Path("assets/models_staging/clean-1-001")
report = json.loads((ROOT / "training_report.json").read_text())
plan_recs = {r["path"]: r for r in report["plan"]["recordings"]}
out = {}


def load(path):
    r = plan_recs[path]
    with contextlib.redirect_stdout(io.StringIO()):
        f = rec.load_recording(rec.Recording(r["vehicle"], Path("assets") / path, r["fmt"], r["frame_cap"]))
    f = rec.chronological(f)
    x, ready = canonical.compute_features_frame(f)
    return x[ready], f["can_id"].to_numpy()[ready]


for fam in sorted(p.name for p in ROOT.iterdir() if (p / "manifest.json").is_file()):
    m = load_family_model(ROOT, fam)
    parts = [(r["path"], *load(r["path"])) for r in m.manifest["training_corpus"]["recordings"]]
    x = np.vstack([p[1] for p in parts]); ids = np.concatenate([p[2] for p in parts])
    src = np.concatenate([np.full(len(p[1]), i) for i, p in enumerate(parts)])
    raw = m.model.decision_function(m.scaler.transform(x[:, m.feature_index]))
    flag = raw < m.threshold
    th = m.manifest["threshold"]
    # decision-score shape: where the threshold sits relative to the distribution
    shape = {"threshold": m.threshold, "median": th["median"], "mad": th["mad"],
             "share_below_threshold": float(flag.mean()),
             "share_below_p02_equivalent": 0.02,
             "decision_p02": float(np.percentile(raw, 2)),
             "skew_left_tail_p01_to_median": float(th["median"] - np.percentile(raw, 1)),
             "right_tail_median_to_p99": float(np.percentile(raw, 99) - th["median"])}
    df = pd.DataFrame({"id": ids, "flag": flag})
    g = df.groupby("id").agg(rows=("flag", "size"), flag_rate=("flag", "mean"))
    g["share"] = g["rows"] / len(df)
    rare = g[g["share"] < 0.01]; common = g[g["share"] >= 0.01]
    bands = {}
    for lo, hi in ((0, 0.001), (0.001, 0.01), (0.01, 0.05), (0.05, 1.01)):
        s = g[(g["share"] >= lo) & (g["share"] < hi)]
        rows = int(s["rows"].sum())
        bands[f"id_share_{lo}-{hi}"] = {"ids": int(len(s)), "rows": rows,
                                        "flag_rate": float((s["rows"] * s["flag_rate"]).sum() / rows) if rows else None}
    per_src = [{"path": p[0], "rows": int((src == i).sum()), "flag_rate": float(flag[src == i].mean())}
               for i, p in enumerate(parts)]
    top = g.sort_values("flag_rate", ascending=False)
    out[fam] = {"decision_shape": shape, "id_volume_bands": bands, "per_source": per_src,
                "train_ids_fully_flagged": int((g["flag_rate"] > 0.99).sum()), "train_ids": int(len(g)),
                "rows_on_fully_flagged_ids": int(g.loc[g["flag_rate"] > 0.99, "rows"].sum()),
                "train_per_id": {f"0x{int(i):X}": {"rows": int(r.rows), "share": float(r.share), "flag_rate": float(r.flag_rate)}
                                 for i, r in g.iterrows()}}
    print(fam, json.dumps({k: out[fam][k] for k in ("decision_shape", "id_volume_bands", "per_source",
                                                   "train_ids_fully_flagged", "train_ids", "rows_on_fully_flagged_ids")}), flush=True)

Path(sys.argv[1]).write_text(json.dumps(out, indent=2), encoding="utf-8")
