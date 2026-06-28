"""
plot_results.py
===============
Reads comparison_pid.json and comparison_random.json from outputs/
and produces two publication-quality graphs saved as PNG files.

Install dependency first:
    pip install matplotlib --break-system-packages

Run from project root:
    python3 scripts/plot_results.py
"""

import os
import json
import sys

try:
    import matplotlib
    matplotlib.use("Agg")          # no display needed — saves directly to file
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
except ImportError:
    print("ERROR: matplotlib not installed.")
    print("Fix : pip install matplotlib --break-system-packages")
    sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
# Style constants
# ─────────────────────────────────────────────────────────────────────────────
BLUE   = "#2E5496"   # FuzzyPID / Clustered  (your project's colour)
ORANGE = "#C0504D"   # Fixed-rate / Random
GREEN  = "#4BACC6"   # accent line
GREY   = "#7F7F7F"

plt.rcParams.update({
    "font.family":      "DejaVu Sans",
    "font.size":        11,
    "axes.titlesize":   13,
    "axes.titleweight": "bold",
    "axes.labelsize":   11,
    "axes.spines.top":  False,
    "axes.spines.right":False,
    "legend.framealpha":0.9,
    "figure.dpi":       150,
})


# ─────────────────────────────────────────────────────────────────────────────
# Graph 1 — FuzzyPID vs Fixed Rate
# ─────────────────────────────────────────────────────────────────────────────
def plot_pid_comparison(data, out_path):
    fixed  = data["fixed"]
    fuzzy  = data["fuzzy"]

    fig, axes = plt.subplots(1, 3, figsize=(14, 4.5))
    fig.suptitle(
        "Graph 1: FuzzyPID Rate Control  vs  Fixed-Rate Probing",
        fontsize=14, fontweight="bold", y=1.02
    )

    # ── Sub-plot A: Probe rate over time ──────────────────────────────────────
    ax = axes[0]
    for d, color, label in [
        (fixed, ORANGE, "Fixed Rate (no PID)"),
        (fuzzy, BLUE,   "FuzzyPID (our system)"),
    ]:
        if d["trace"]:
            ts    = [p["t"]    for p in d["trace"]]
            rates = [p["rate"] for p in d["trace"]]
            ax.plot(ts, rates, color=color, linewidth=2, label=label)

    ax.set_title("Probe Rate Over Time")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Probe Rate (pps)")
    ax.legend(fontsize=9)
    ax.set_ylim(bottom=0)

    # ── Sub-plot B: RTT over time ─────────────────────────────────────────────
    ax = axes[1]
    for d, color, label in [
        (fixed, ORANGE, "Fixed Rate"),
        (fuzzy, BLUE,   "FuzzyPID"),
    ]:
        if d["trace"]:
            ts   = [p["t"]   for p in d["trace"]]
            rtts = [p["rtt"] for p in d["trace"]]
            ax.plot(ts, rtts, color=color, linewidth=2, label=label)

    ax.set_title("RTT Over Time")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("RTT (ms)")
    ax.legend(fontsize=9)
    ax.set_ylim(bottom=0)

    # ── Sub-plot C: Summary bar chart ─────────────────────────────────────────
    ax = axes[2]
    metrics = ["Hit Rate (%)", "False Positives", "Time (s)"]
    f_vals  = [fixed["hit_rate"], fixed["false_pos"], fixed["elapsed"]]
    z_vals  = [fuzzy["hit_rate"], fuzzy["false_pos"], fuzzy["elapsed"]]

    x      = range(len(metrics))
    width  = 0.35
    bars_f = ax.bar([xi - width/2 for xi in x], f_vals, width,
                    color=ORANGE, label="Fixed Rate", alpha=0.85)
    bars_z = ax.bar([xi + width/2 for xi in x], z_vals, width,
                    color=BLUE,   label="FuzzyPID",   alpha=0.85)

    # Value labels on bars
    for bar in list(bars_f) + list(bars_z):
        h = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2, h + 0.5,
                f"{h:.1f}", ha="center", va="bottom", fontsize=8)

    ax.set_title("Summary Metrics")
    ax.set_xticks(list(x))
    ax.set_xticklabels(metrics, fontsize=9)
    ax.set_ylabel("Value")
    ax.legend(fontsize=9)
    ax.set_ylim(bottom=0)

    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    print(f"  Saved → {out_path}")
    plt.close(fig)


# ─────────────────────────────────────────────────────────────────────────────
# Graph 2 — Random vs Clustered Probing
# ─────────────────────────────────────────────────────────────────────────────
def plot_random_comparison(data, out_path):
    rnd = data["random"]
    clu = data["clustered"]

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
    fig.suptitle(
        "Graph 2: Cluster-Guided Probing  vs  Random Probing",
        fontsize=14, fontweight="bold", y=1.02
    )

    # ── Sub-plot A: Discovery curve (cumulative hits vs probes sent) ───────────
    ax = axes[0]
    ax.plot(rnd["curve_probes"], rnd["curve_hits"],
            color=ORANGE, linewidth=2.5, marker="o", markersize=4,
            label="Random Probing")
    ax.plot(clu["curve_probes"], clu["curve_hits"],
            color=BLUE,   linewidth=2.5, marker="s", markersize=4,
            label="Cluster-Guided (6Map)")

    # Mark final discovered counts
    ax.axhline(rnd["active"], color=GREY, linestyle="--", linewidth=1,
               label=f"Total active hosts ({rnd['active']})")

    ax.set_title("Active Hosts Discovered vs Probes Sent")
    ax.set_xlabel("Number of Probes Sent")
    ax.set_ylabel("Cumulative Active Hosts Found")
    ax.legend(fontsize=9)
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0)

    # ── Sub-plot B: Bar comparison of final metrics ────────────────────────────
    ax = axes[1]
    categories = ["Hit Rate (%)", "False Positives", "Time (s)"]
    r_vals = [rnd["hit_rate"], rnd["false_pos"], rnd["elapsed"]]
    c_vals = [clu["hit_rate"], clu["false_pos"], clu["elapsed"]]

    x     = range(len(categories))
    width = 0.35
    br    = ax.bar([xi - width/2 for xi in x], r_vals, width,
                   color=ORANGE, label="Random",        alpha=0.85)
    bc    = ax.bar([xi + width/2 for xi in x], c_vals, width,
                   color=BLUE,   label="Cluster-Guided", alpha=0.85)

    for bar in list(br) + list(bc):
        h = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2, h + 0.5,
                f"{h:.1f}", ha="center", va="bottom", fontsize=8)

    ax.set_title("Final Metrics Comparison")
    ax.set_xticks(list(x))
    ax.set_xticklabels(categories, fontsize=9)
    ax.set_ylabel("Value")
    ax.legend(fontsize=9)
    ax.set_ylim(bottom=0)

    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    print(f"  Saved → {out_path}")
    plt.close(fig)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────
def load_json(path):
    if not os.path.exists(path):
        print(f"ERROR: {path} not found.")
        print("       Run the corresponding comparison script first.")
        return None
    with open(path) as f:
        return json.load(f)


if __name__ == "__main__":
    os.makedirs("outputs", exist_ok=True)

    print("\n── Graph 1: FuzzyPID vs Fixed Rate ──────────────────────────────")
    pid_data = load_json("outputs/comparison_pid.json")
    if pid_data:
        plot_pid_comparison(pid_data, "outputs/graph1_pid_comparison.png")

    print("\n── Graph 2: Random vs Clustered Probing ─────────────────────────")
    rnd_data = load_json("outputs/comparison_random.json")
    if rnd_data:
        plot_random_comparison(rnd_data, "outputs/graph2_random_vs_clustered.png")

    print("\nDone. Check the outputs/ folder for PNG files.")
