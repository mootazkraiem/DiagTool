"""Render holdout_analysis.md from the two analysis JSON files (read-only inputs)."""
import json
import sys
from pathlib import Path

D = Path(sys.argv[1])
H = json.loads((D / "holdout_analysis.json").read_text())
T = json.loads((D / "training_id_analysis.json").read_text())
L = []
w = L.append


def pc(v):
    return f"{v * 100:.2f}%"


w("# clean-1-001 — holdout analysis (read-only)\n")
w("Generated for Step 10E. No model, scaler, threshold, manifest or production file was changed. "
  "Data: `holdout_analysis.json` (holdout vs training) and `training_id_analysis.json` (training-side "
  "per-CAN-ID results); scripts: `step10e_analyze.py`, `step10e_supp.py`, `step10e_report.py`.\n")
w("A row is *flagged* when the family's normalised score is >= 0.5, i.e. its IsolationForest decision "
  "value is below the family threshold. Holdout recordings are unlabelled captures assumed to be normal "
  "operation, so the rates below are **holdout flagged rates** (unseen normal traffic flagged), not "
  "false-positive rates.\n")

w("## Summary\n")
w("| Family | Holdout flagged | Training flagged | Holdout IDs unseen in training | Training IDs flagged 100% in training | Top-10 IDs' share of holdout flags |")
w("|---|---|---|---|---|---|")
for f, r in H.items():
    t = T[f]
    w(f"| {f} | {r['holdout_flagged']:,}/{r['holdout_rows']:,} ({pc(r['holdout_flag_rate'])}) "
      f"| {pc(t['decision_shape']['share_below_threshold'])} "
      f"| {len(r['can_ids']['holdout_only'])}/{r['can_ids']['holdout']} ({r['holdout_rows_on_unseen_ids']:,} rows) "
      f"| {t['train_ids_fully_flagged']}/{t['train_ids']} | {r['top10_share_of_flags'] * 100:.1f}% |")
w("")
w("Families without a holdout (training flagged rate only): " + ", ".join(
    f"{f} {pc(T[f]['decision_shape']['share_below_threshold'])}" for f in T if f not in H) + ".\n")

w((Path(sys.argv[2]).read_text(encoding="utf-8")))

w("## Training flagged rate by CAN-ID volume (training rows)\n")
w("| Family | IDs < 0.1% of rows | 0.1-1% | 1-5% | >= 5% |")
w("|---|---|---|---|---|")
for f, t in T.items():
    cells = ["—" if not v["rows"] else f"{pc(v['flag_rate'])} ({v['ids']} IDs, {v['rows']:,} rows)"
             for v in t["id_volume_bands"].values()]
    w(f"| {f} | " + " | ".join(cells) + " |")
w("")
w("## Threshold position per family (training decision values)\n")
w("| Family | Threshold | Median | MAD | Decision p02 | Median - p01 | p99 - median | Training flagged |")
w("|---|---|---|---|---|---|---|---|")
for f, t in T.items():
    s = t["decision_shape"]
    w(f"| {f} | {s['threshold']:.4f} | {s['median']:.4f} | {s['mad']:.4f} | {s['decision_p02']:.4f} "
      f"| {s['skew_left_tail_p01_to_median']:.3f} | {s['right_tail_median_to_p99']:.3f} | {pc(s['share_below_threshold'])} |")
w("")

for f, r in H.items():
    t = T[f]
    src = {p["path"]: p["flag_rate"] for p in t["per_source"]}
    w(f"## {f}\n")
    w(f"Features used: {', '.join(r['features'])}. Threshold {r['threshold']:.6f}.\n")
    w("| Recording | Role | Format | Frames | Duration s | Frames/s | IDs | Whole-ms steps | Training flagged |")
    w("|---|---|---|---|---|---|---|---|---|")
    for m in r["train_recordings"]:
        w(f"| {m['path']} | train | {m['fmt']} | {m['frames']:,} | {m['duration_s']:.1f} | {m['fps']:.1f} "
          f"| {m['can_ids']} | {m['share_steps_whole_ms']:.3f} | {pc(src.get(m['path'], 0))} |")
    for m in r["holdout_recordings"]:
        w(f"| {m['path']} | holdout | {m['fmt']} | {m['frames']:,} | {m['duration_s']:.1f} | {m['fps']:.1f} "
          f"| {m['can_ids']} | {m['share_steps_whole_ms']:.3f} | — |")
    w("")
    keys = list(r["train_score_pct"])
    w("| Score | " + " | ".join(keys) + " |")
    w("|---|" + "---|" * len(keys))
    for label, k in (("training, normalised", "train_score_pct"), ("holdout, normalised", "holdout_score_pct"),
                     ("training, decision", "train_decision_pct"), ("holdout, decision", "holdout_decision_pct")):
        w(f"| {label} | " + " | ".join(f"{v:.3f}" for v in r[k].values()) + " |")
    w(f"\nTraining rows scored for percentiles: {r['train_rows_scored']:,} of {r['train_rows']:,} "
      f"(every {r['train_score_stride']}th row); training flagged rate above uses all rows.\n")
    w("| Feature | KS | Train p50 | Holdout p50 | Holdout outside train p0.5-p99.5 | Flagged rows outside | Flagged rows un-flagged when set to train median |")
    w("|---|---|---|---|---|---|---|")
    for n, fc in r["feature_comparison"].items():
        if not fc["used"]:
            continue
        fo = fc["flagged_outside_train_p0.5_p99.5"]
        w(f"| {n} | {fc['ks']:.3f} | {fc['train']['p50']:.3f} | {fc['holdout']['p50']:.3f} "
          f"| {pc(fc['holdout_outside_train_p0.5_p99.5'])} | {'' if fo is None else pc(fo)} "
          f"| {r['ablation_unflag_share'].get(n, 0) * 100:.1f}% |")
    w(f"\nCAN IDs: training {r['can_ids']['train']}, holdout {r['can_ids']['holdout']}, shared "
      f"{r['can_ids']['shared']}, holdout-only: {', '.join(r['can_ids']['holdout_only']) or 'none'}.\n")
    w("| CAN ID | Holdout rows | Flagged | Holdout flagged rate | Training rows | Training flagged rate | Period ms per training recording | Period ms holdout |")
    w("|---|---|---|---|---|---|---|---|")
    for p in r["top_flagged_ids"]:
        tf = t["train_per_id"].get(p["can_id"])
        per = ", ".join(f"{x:.1f}" for x in p["train_median_period_ms"] if x is not None) or "—"
        hp = p["holdout_median_period_ms"]
        w(f"| {p['can_id']} | {p['holdout_rows']:,} | {p['flagged']:,} | {p['flag_rate'] * 100:.1f}% "
          f"| {p['train_rows']:,} | {'—' if not tf else pc(tf['flag_rate'])} | {per} | {'' if hp is None else f'{hp:.1f}'} |")
    w(f"\nTop-10 IDs account for {r['top10_share_of_flags'] * 100:.1f}% of holdout flags. "
      "Full per-ID table: `holdout_analysis.json`.\n")

(D / "holdout_analysis.md").write_text("\n".join(L), encoding="utf-8")
print("written", len(L), "lines")
