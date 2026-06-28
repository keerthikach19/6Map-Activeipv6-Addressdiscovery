"""
comparison_random.py
====================
Option 3: Random probing  vs  Cluster-guided probing

In Mininet, active hosts live at 2001:db8:1::<i> for i in 1..N.

  Random   → probe N-1 random last-hextet values from 0x0000–0xffff
  Clustered → probe the actual sequential addresses (as your system does)

Saves results to:
    outputs/comparison_random.json

Run as root:
    sudo python3 scripts/comparison_random.py --hosts 50 --active-ratio 0.7
"""

import os
import sys
import time
import json
import random
import threading
import re
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "control_plane"))

from mininet_bmv2 import create_p4_network
from fuzzy_pid import set_switch_meter_rate


# ─────────────────────────────────────────────────────────────────────────────
# Prober: runs a list of target addresses, returns (discovered, elapsed,
#         per-step hit counts for the discovery-over-time curve)
# ─────────────────────────────────────────────────────────────────────────────
def run_prober(h1, target_addrs, batch=20, timeout=3):
    targets_file = f"/tmp/rnd_targets_{h1.name}.txt"
    results_file = f"/tmp/rnd_results_{h1.name}.txt"
    script_file  = f"/tmp/rnd_probe_{h1.name}.sh"

    with open(targets_file, "w") as f:
        for a in target_addrs:
            f.write(a + "\n")

    script = f"""#!/bin/bash
> "{results_file}"
count=0
while IFS= read -r addr; do
    ( ping6 -c 1 -W {timeout} "$addr" > /dev/null 2>&1 && echo "$addr" >> "{results_file}" ) &
    count=$((count + 1))
    if [ $((count % {batch})) -eq 0 ]; then
        wait
    fi
done < "{targets_file}"
wait
"""
    with open(script_file, "w") as f:
        f.write(script)
    os.chmod(script_file, 0o755)

    start = time.time()
    h1.cmd(f"bash {script_file}")
    elapsed = time.time() - start

    active = set()
    if os.path.exists(results_file):
        with open(results_file) as f:
            active = {l.strip() for l in f if l.strip()}

    return active, elapsed


# ─────────────────────────────────────────────────────────────────────────────
# Build probe target lists for each strategy
# ─────────────────────────────────────────────────────────────────────────────
def make_random_targets(num_hosts, seed=42):
    """
    Pick (num_hosts - 1) random last-hextet values from 0x0001–0xffff,
    excluding ::1 (the prober h1).
    This simulates blind random IPv6 scanning within the /64 subnet.
    """
    rng = random.Random(seed)
    pool = list(range(2, 0x10000))          # 0x0002 … 0xffff
    chosen = rng.sample(pool, num_hosts - 1)
    return [f"2001:db8:1::{hex(v)[2:]}" for v in chosen]


def make_clustered_targets(num_hosts):
    """
    Cluster-guided: we know addresses follow 2001:db8:1::<sequential>.
    This is exactly what the clustering algorithm discovered from the
    synthetic mininet dataset.
    """
    return [f"2001:db8:1::{i}" for i in range(2, num_hosts + 1)]


# ─────────────────────────────────────────────────────────────────────────────
# Build the incremental discovery curve
# (how many active hosts found after probing k addresses)
# ─────────────────────────────────────────────────────────────────────────────
def discovery_curve(target_list, ground_truth, step=5):
    """
    Simulate sequential probing and record cumulative hits.
    Returns two lists: probes_sent[], cumulative_hits[]
    """
    gt = set(ground_truth)
    found = 0
    probes  = []
    hits    = []
    for i, addr in enumerate(target_list, start=1):
        if addr in gt:
            found += 1
        if i % step == 0 or i == len(target_list):
            probes.append(i)
            hits.append(found)
    return probes, hits


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--hosts",        type=int,   default=50)
    parser.add_argument("--active-ratio", type=float, default=0.7)
    args = parser.parse_args()

    from mininet.log import setLogLevel
    setLogLevel("warning")

    results = {}

    for mode in ["random", "clustered"]:
        print(f"\n{'='*60}")
        print(f"  Running: {'Random probing' if mode=='random' else 'Cluster-guided probing'}")
        print(f"{'='*60}")

        net, hosts, active_addrs = create_p4_network(
            num_hosts=args.hosts, active_ratio=args.active_ratio)
        h1 = hosts[0]

        ground_truth = set(active_addrs) - {h1.ipv6}

        if mode == "random":
            target_addrs = make_random_targets(args.hosts)
        else:
            target_addrs = make_clustered_targets(args.hosts)

        # Set a fixed meter rate so both runs are fair
        set_switch_meter_rate(100)

        discovered, elapsed = run_prober(h1, target_addrs)

        tp  = discovered & ground_truth
        fp  = discovered - ground_truth
        hit = len(tp) / len(ground_truth) * 100 if ground_truth else 0

        # Build discovery-over-time curve (offline simulation using probe order)
        probes, cum_hits = discovery_curve(target_addrs, ground_truth, step=max(1, args.hosts // 20))

        results[mode] = {
            "mode":       mode,
            "hosts":      args.hosts,
            "active":     len(ground_truth),
            "discovered": len(tp),
            "hit_rate":   round(hit, 2),
            "false_pos":  len(fp),
            "elapsed":    round(elapsed, 2),
            "curve_probes": probes,
            "curve_hits":   cum_hits,
        }

        print(f"  Targets probed : {len(target_addrs)}")
        print(f"  Active found   : {len(tp)} / {len(ground_truth)}")
        print(f"  Hit rate       : {hit:.1f}%")
        print(f"  False positives: {len(fp)}")
        print(f"  Elapsed        : {elapsed:.1f}s")

        net.stop()
        time.sleep(3)

    os.makedirs("outputs", exist_ok=True)
    out_path = "outputs/comparison_random.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved → {out_path}")
