"""Charts of the algorithm comparison (Chapter 5, section sec:validation-compare).

Every number comes from backend/ml/outputs/validation_reports/algorithm_comparison.json,
written by python -m backend.ml.validation.compare_algorithms --cap 5000.
"""
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).resolve().parent
REPORT = HERE.parents[2] / "backend" / "ml" / "outputs" / "validation_reports" / "algorithm_comparison.json"
r = json.loads(REPORT.read_text(encoding="utf-8"))

BG, PANEL, GRID, TEXT, MUTED = "#0b0f19", "#0b0f19", "#1f2937", "#f3f4f6", "#9ca3af"
GREEN, BLUE, GREY = "#00c896", "#3b82f6", "#94a3b8"
ALGOS = [("isolation_forest", "Isolation Forest", GREEN), ("lof", "LOF", BLUE), ("one_class_svm", "One Class SVM", GREY)]
NAMES = {"jaguar_ipace": "Jaguar I-PACE", "kia_ev6": "Kia EV6", "nissan_leaf_2019": "Nissan Leaf 2019",
         "road_ambient": "ROAD"}

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 12, "text.color": TEXT, "axes.labelcolor": MUTED,
                     "xtick.color": MUTED, "ytick.color": MUTED, "axes.edgecolor": "#4b5563"})


def dark(ax, title):
    ax.set_facecolor(PANEL)
    ax.set_title(title, color=TEXT, fontsize=14, fontweight="bold", pad=12)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


# 1. Share of holdout rows flagged, per vehicle and algorithm
fams = r["families"]
fig, ax = plt.subplots(figsize=(11, 5.2), facecolor=BG)
dark(ax, "Share of holdout rows flagged (normal traffic, target 2%)")
x = np.arange(len(fams))
w = 0.26
top = 0
for i, (key, label, color) in enumerate(ALGOS):
    vals = [100 * f["algorithms"][key]["flagged_share"] for f in fams]
    top = max(top, max(vals))
    bars = ax.bar(x + (i - 1) * w, vals, w * 0.92, color=color, label=label)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.4, f"{v:.1f}%", ha="center", va="bottom", fontsize=10.5,
                color=TEXT, fontweight="bold")
ax.axhline(2, color="#f87171", linestyle="--", linewidth=1.4, label="calibration target 2%")
ax.set_xticks(x, [NAMES[f["family"]] for f in fams], color=TEXT)
ax.set_ylabel("Holdout rows flagged (%)")
ax.set_ylim(0, top * 1.18)
ax.legend(facecolor="#111827", edgecolor="#4b5563", labelcolor=TEXT, loc="upper right", ncol=2, fontsize=10.5)
fig.tight_layout()
fig.savefig(HERE / "ml_compare_flagged.png", dpi=200, facecolor=BG)
plt.close(fig)

# 2. Cost: training time and time to score one frame
fig, axes = plt.subplots(1, 2, figsize=(11, 4.6), facecolor=BG)
fit = [sum(f["algorithms"][k]["fit_s"] for f in fams) for k, _, _ in ALGOS]
one = [float(np.median([f["algorithms"][k]["single_call_ms_median"] for f in fams])) for k, _, _ in ALGOS]
for ax, title, vals, unit, fmt in ((axes[0], "Training time, 4 vehicles", fit, "Seconds", "{:.0f} s"),
                                   (axes[1], "Time to score one frame", one, "Milliseconds (median)", "{:.2f} ms")):
    dark(ax, title)
    bars = ax.bar([a[1] for a in ALGOS], vals, 0.55, color=[a[2] for a in ALGOS])
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v * 1.02 + max(vals) * 0.01, fmt.format(v), ha="center",
                va="bottom", fontsize=11, color=TEXT, fontweight="bold")
    ax.set_ylabel(unit)
    ax.set_ylim(0, max(vals) * 1.2)
    ax.tick_params(axis="x", colors=TEXT)
fig.tight_layout()
fig.savefig(HERE / "ml_compare_cost.png", dpi=200, facecolor=BG)
plt.close(fig)

# 3. Features used by the final forests
shares = sorted(r["forest_feature_shares"]["share"].items(), key=lambda kv: kv[1])
fig, ax = plt.subplots(figsize=(11, 5.4), facecolor=BG)
dark(ax, f"Features used by the final Isolation Forests ({r['forest_feature_shares']['models']} identifiers)")
ax.grid(axis="x", color=GRID, linewidth=0.8)
ax.grid(axis="y", visible=False)
vals = [100 * v for _, v in shares]
colors = [GREEN if v >= 15 else BLUE if v >= 5 else GREY for v in vals]
bars = ax.barh([k for k, _ in shares], vals, 0.62, color=colors)
for b, v in zip(bars, vals):
    ax.text(v + 0.3, b.get_y() + b.get_height() / 2, f"{v:.1f}%", va="center", fontsize=10.5, color=TEXT)
ax.set_xlabel("Share of the splits, weighted by the training rows reaching them (%)")
ax.set_xlim(0, max(vals) * 1.15)
ax.tick_params(axis="y", colors=TEXT)
from matplotlib.patches import Patch
ax.legend(handles=[Patch(color=GREEN, label="15% or more"), Patch(color=BLUE, label="5% to 15%"),
                   Patch(color=GREY, label="under 5%")], facecolor="#111827", edgecolor="#4b5563",
          labelcolor=TEXT, loc="lower right")
fig.tight_layout()
fig.savefig(HERE / "ml_feature_shares.png", dpi=200, facecolor=BG)
plt.close(fig)
print("saved ml_compare_flagged.png, ml_compare_cost.png, ml_feature_shares.png")
