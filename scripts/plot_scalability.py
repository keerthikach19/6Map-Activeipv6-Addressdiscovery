"""
plot_scalability.py
===================
Plots the scale experiment results showing:
  1. Hit Rate vs Host Count  (with breaking point annotation)
  2. Time vs Host Count      (linear scaling)
  3. Active Hosts Found vs Total Hosts

Run from project root:
    python3 scripts/plot_scalability.py
"""

import os
import sys

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    from matplotlib.lines import Line2D
except ImportError:
    print("ERROR: matplotlib not installed.")
    print("Fix  : pip install matplotlib --break-system-packages")
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────────────────
# Raw results data (from your actual experiment runs)
# ─────────────────────────────────────────────────────────────────────────────
RAW = [
    # hosts, active, found, hit_pct, time_s
    (100,   69,   69,  100.0,  15.6),
    (200,  139,  139,  100.0,  30.8),
    (300,  209,  209,  100.0,  46.2),
    (500,  349,  349,  100.0,  76.9),   # first 500 run (success)
    (501,  349,  349,  100.0,  76.3),
    (505,  352,  352,  100.0,  80.2),
    (506,  353,  353,  100.0,  79.6),
    (507,  353,  353,  100.0,  77.7),
    (508,  354,    0,    0.0,  80.4),   # ← BREAKING POINT
    (510,  356,    0,    0.0,  79.2),
    (530,  370,    0,    0.0,  82.2),
    (550,  384,    0,    0.0,  85.3),
    (600,  419,    0,    0.0,  92.3),
    (700,  488,    0,    0.0, 107.4),
    (1000, 699,    0,    0.0, 153.4),
]

# Sort by host count for clean lines
RAW.sort(key=lambda r: r[0])

hosts  = [r[0] for r in RAW]
active = [r[1] for r in RAW]
found  = [r[2] for r in RAW]
hits   = [r[3] for r in RAW]
times  = [r[4] for r in RAW]

BREAKING_POINT = 508   # first host count where hit rate drops to 0

# Split into success / failure zones
hosts_ok  = [r[0] for r in RAW if r[0] <= 507]
hits_ok   = [r[3] for r in RAW if r[0] <= 507]
times_ok  = [r[4] for r in RAW if r[0] <= 507]
found_ok  = [r[2] for r in RAW if r[0] <= 507]

hosts_fail  = [r[0] for r in RAW if r[0] >= 508]
hits_fail   = [r[3] for r in RAW if r[0] >= 508]
times_fail  = [r[4] for r in RAW if r[0] >= 508]
found_fail  = [r[2] for r in RAW if r[0] >= 508]

# ─────────────────────────────────────────────────────────────────────────────
# Colour palette  (project colours)
# ─────────────────────────────────────────────────────────────────────────────
BLUE    = "#2E5496"
RED     = "#C0504D"
GREEN   = "#4BACC6"
ORANGE  = "#E36C09"
LGREY   = "#D9D9D9"
DGREY   = "#595959"

plt.rcParams.update({
    "font.family":      "DejaVu Sans",
    "font.size":        11,
    "axes.titlesize":   12,
    "axes.titleweight": "bold",
    "axes.labelsize":   11,
    "axes.spines.top":  False,
    "axes.spines.right":False,
    "legend.framealpha":0.9,
    "figure.dpi":       150,
})


# ─────────────────────────────────────────────────────────────────────────────
# Figure layout: 1 row × 3 sub-plots
# ─────────────────────────────────────────────────────────────────────────────
fig, axes = plt.subplots(1, 3, figsize=(15, 5))
fig.suptitle(
    "Graph 3: 6Map System Scalability — Breaking Point Analysis",
    fontsize=14, fontweight="bold", y=1.02
)


# ── Sub-plot 1: Hit Rate vs Host Count ───────────────────────────────────────
ax = axes[0]

ax.plot(hosts_ok,   hits_ok,   color=BLUE,  linewidth=2.5,
        marker="o", markersize=6, label="100% Hit Rate")
ax.plot(hosts_fail, hits_fail, color=RED,   linewidth=2.5,
        marker="x", markersize=8, label="0% Hit Rate (failed)")

# Breaking point vertical line
ax.axvline(x=BREAKING_POINT, color=ORANGE, linestyle="--",
           linewidth=1.8, label=f"Breaking point ({BREAKING_POINT} hosts)")

# Shaded zones
ax.axvspan(0, BREAKING_POINT, alpha=0.06, color=BLUE)
ax.axvspan(BREAKING_POINT, max(hosts)+50, alpha=0.06, color=RED)

# Annotation
ax.annotate(
    f"System limit\n≈507 hosts",
    xy=(BREAKING_POINT, 50),
    xytext=(BREAKING_POINT + 60, 60),
    fontsize=9,
    color=ORANGE,
    arrowprops=dict(arrowstyle="->", color=ORANGE, lw=1.3),
)

ax.set_title("Hit Rate vs Number of Hosts")
ax.set_xlabel("Total Hosts")
ax.set_ylabel("Hit Rate (%)")
ax.set_ylim(-5, 115)
ax.set_xlim(left=0)
ax.legend(fontsize=9)


# ── Sub-plot 2: Time vs Host Count ───────────────────────────────────────────
ax = axes[1]

ax.plot(hosts_ok,   times_ok,   color=BLUE,  linewidth=2.5,
        marker="o", markersize=6, label="Successful runs")
ax.plot(hosts_fail, times_fail, color=RED,   linewidth=2.5,
        marker="x", markersize=8, linestyle="--", label="Failed runs (0% hit)")

ax.axvline(x=BREAKING_POINT, color=ORANGE, linestyle="--",
           linewidth=1.8, label=f"Breaking point")

# Linear trend line through successful points only
if len(hosts_ok) >= 2:
    import statistics
    n    = len(hosts_ok)
    xbar = sum(hosts_ok) / n
    ybar = sum(times_ok) / n
    num  = sum((hosts_ok[i]-xbar)*(times_ok[i]-ybar) for i in range(n))
    den  = sum((hosts_ok[i]-xbar)**2 for i in range(n))
    slope = num / den if den else 0
    inter = ybar - slope * xbar
    x_trend = [min(hosts_ok), BREAKING_POINT]
    y_trend = [slope*x + inter for x in x_trend]
    ax.plot(x_trend, y_trend, color=GREEN, linewidth=1.5,
            linestyle=":", label="Linear trend")

ax.set_title("Elapsed Time vs Number of Hosts")
ax.set_xlabel("Total Hosts")
ax.set_ylabel("Time (seconds)")
ax.set_xlim(left=0)
ax.set_ylim(bottom=0)
ax.legend(fontsize=9)


# ── Sub-plot 3: Active Hosts Found vs Active Hosts Present ───────────────────
ax = axes[2]

# Ideal line  (found == active)
ax.plot([0, max(active)], [0, max(active)],
        color=LGREY, linewidth=1.5, linestyle="--", label="Ideal (found = active)")

ax.scatter([r[1] for r in RAW if r[0] <= 507],
           [r[2] for r in RAW if r[0] <= 507],
           color=BLUE, s=70, zorder=5, label="Successful runs")

ax.scatter([r[1] for r in RAW if r[0] >= 508],
           [r[2] for r in RAW if r[0] >= 508],
           color=RED, s=70, marker="x", linewidths=2,
           zorder=5, label="Failed runs")

# Annotate a couple of key points
for hosts_n, act, fnd, hit, t in RAW:
    if hosts_n in (100, 300, 507, 508, 1000):
        ax.annotate(
            f"{hosts_n}h",
            xy=(act, fnd),
            xytext=(act + 8, fnd + 5),
            fontsize=8,
            color=BLUE if hit > 0 else RED,
        )

ax.set_title("Hosts Found vs Hosts Present")
ax.set_xlabel("Active Hosts in Network")
ax.set_ylabel("Active Hosts Discovered")
ax.set_xlim(left=0)
ax.set_ylim(bottom=0)
ax.legend(fontsize=9)


# ─────────────────────────────────────────────────────────────────────────────
# Save
# ─────────────────────────────────────────────────────────────────────────────
os.makedirs("outputs", exist_ok=True)
out_path = "outputs/graph3_scalability.png"
fig.tight_layout()
fig.savefig(out_path, bbox_inches="tight")
print(f"Saved → {out_path}")
plt.close(fig)
