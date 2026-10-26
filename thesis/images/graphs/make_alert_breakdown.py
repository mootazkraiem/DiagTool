"""Severity and dominant layer of the 11,971 alerts of the corrected first pipeline
(Chapter 5, Figure fig:chart-severity). The counts are those of the replay summary
of the corrected pipeline on the Kia EV6 recording, as reported in the thesis.
"""
import matplotlib.pyplot as plt

panels = [
    ("Severity", ["LOW", "MEDIUM", "HIGH", "CRITICAL"], [4748, 2069, 2279, 2875],
     ["#3b6fa0", "#d08a2c", "#b5443b", "#7a1f1f"]),
    ("Dominant layer after Fix 3", ["Timing\n(timing_burst)", "Payload\n(continuity_break)", "Model\n(ml_outlier)"],
     [5031, 4451, 2489], ["#3b6fa0", "#3e8e5e", "#d08a2c"]),
]

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 12})
fig, axes = plt.subplots(1, 2, figsize=(12, 4.4))
for ax, (title, labels, values, colors) in zip(axes, panels):
    bars = ax.bar(labels, values, color=colors, width=0.6)
    for bar, v in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, v + 90, f"{v:,}", ha="center", va="bottom", fontweight="bold")
    ax.set_title(title, fontsize=14)
    ax.set_ylabel("Number of alerts")
    ax.set_ylim(0, 6000)
    ax.grid(axis="y", alpha=0.3)
    ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout()
fig.savefig("alert_breakdown.png", dpi=200)
print("saved alert_breakdown.png")
