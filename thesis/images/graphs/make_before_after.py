"""Before/after chart of the first iteration (Chapter 5, Table tab:before-after).

Every value is the one of the table: 15,945 -> 11,971 alerts, a saturated model
score on 77.6 to 78.6% of the frames -> 0.0%, and a replay throughput of about
143 -> 194.6 frames/s (97,741 frames in 685 s and in 502.2 s).
"""
import matplotlib.pyplot as plt

RED, GREEN = "#b5443b", "#3e8e5e"
panels = [
    ("Total alerts", "Alerts on the 97,741-frame recording", [15945, 11971], ["15,945", "11,971"], 18000),
    ("Saturated model score", "Frames with model score $\\geq$ 0.999 (%)", [78.6, 0.0], ["77.6 to 78.6%", "0.0%"], 90),
    ("Replay throughput", "Frames per second", [142.7, 194.6], ["about 143", "194.6"], 230),
]

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11})
fig, axes = plt.subplots(1, 3, figsize=(13.5, 4.2))
for ax, (title, ylabel, values, labels, ymax) in zip(axes, panels):
    bars = ax.bar(["Before\ncorrection", "After\ncorrection"], values, color=[RED, GREEN], width=0.5)
    for bar, text in zip(bars, labels):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + ymax * 0.015, text,
                ha="center", va="bottom", fontweight="bold")
    ax.set_title(title, fontsize=13)
    ax.set_ylabel(ylabel)
    ax.set_ylim(0, ymax)
    ax.grid(axis="y", alpha=0.3)
    ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout()
fig.savefig("before_after_summary.png", dpi=200)
print("saved before_after_summary.png")
