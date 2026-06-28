"""
comparison_pid.py
=================
Option 1: FuzzyPID-controlled probing  vs  Fixed-rate probing

Runs two back-to-back discovery experiments inside Mininet and
saves per-tick rate/RTT/loss traces plus summary metrics to:
    outputs/comparison_pid.json

Run as root:
    sudo python3 scripts/comparison_pid.py --hosts 50 --active-ratio 0.7
"""

import os
import sys
import time
import json
import random
import threading
import re
import argparse

# ── path setup so imports work from project root ──────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "control_plane"))

from mininet_bmv2 import create_p4_network
from fuzzy_pid import FuzzyPID, set_switch_meter_rate


# ─────────────────────────────────────────────────────────────────────────────
# Helper: single ping
# ─────────────────────────────────────────────────────────────────────────────
def get_ping_rtt(node, target_ip):
    output = node.cmd(f"ping6 -c 1 -W 1 {target_ip}")
    m = re.search(r"time=([\d\.]+)\s*ms", output)
    if m:
        try:
            return float(m.group(1)), True
        except ValueError:
            pass
    return None, False


# ─────────────────────────────────────────────────────────────────────────────
# Prober: parallel ICMPv6 pings, returns (discovered_set, elapsed_s, trace)
# trace = list of dicts {t, rate, rtt, loss}
# ─────────────────────────────────────────────────────────────────────────────
def run_prober_with_trace(h1, h2, target_addrs,
                          use_fuzzy_pid=True,
                          fixed_rate_pps=50,
                          target_rtt_ms=7.0):
    """
    use_fuzzy_pid=True  → FuzzyPID updates the P4 meter every 500 ms
    use_fuzzy_pid=False → meter stays at fixed_rate_pps the whole time
    """
    total    = len(target_addrs)
    batch    = 20
    timeout  = 3

    targets_file = f"/tmp/cmp_targets_{h1.name}.txt"
    results_file = f"/tmp/cmp_results_{h1.name}.txt"
    script_file  = f"/tmp/cmp_probe_{h1.name}.sh"

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

    # ── PID controller (only used when use_fuzzy_pid=True) ───────────────────
    pid_ctrl    = FuzzyPID(kp_init=1.0, ki_init=0.1, kd_init=0.05)
    current_rate = fixed_rate_pps
    rtt_history  = []
    rtt_min      = None
    budget       = 2.0
    measured_rtt = 0.0
    loss_rate    = 0.0
    trace        = []          # [{t, rate, rtt, loss}]
    lock         = threading.Lock()
    rtt_samples  = []

    # Set initial meter rate
    set_switch_meter_rate(current_rate)

    # ── RTT monitor thread ────────────────────────────────────────────────────
    monitor_running = True
    def rtt_monitor():
        while monitor_running:
            rtt, ok = get_ping_rtt(h2, "2001:db8:1::1")
            with lock:
                rtt_samples.append((rtt, ok))
            time.sleep(0.15)

    mon = threading.Thread(target=rtt_monitor)
    mon.daemon = True
    mon.start()

    # ── Control loop thread (only meaningful when use_fuzzy_pid=True) ─────────
    ctrl_running = True
    def control_loop():
        nonlocal current_rate, measured_rtt, loss_rate, rtt_min, budget
        last_t = time.time()
        while ctrl_running:
            time.sleep(0.5)
            now = time.time()
            dt  = now - last_t
            last_t = now

            with lock:
                samples = list(rtt_samples)
                rtt_samples.clear()

            if samples:
                ok_rtts     = [r for r, s in samples if s]
                num_fail    = sum(1 for _, s in samples if not s)
                loss_rate   = num_fail / len(samples)

                if ok_rtts:
                    rtt_history.extend(ok_rtts)
                    if len(rtt_history) > 30:
                        del rtt_history[:-30]
                    rtt_min = min(rtt_history)
                    step_avg = sum(ok_rtts) / len(ok_rtts)
                    measured_rtt = (0.3 * step_avg + 0.7 * measured_rtt
                                    if measured_rtt else step_avg)
                else:
                    measured_rtt = target_rtt_ms + 15.0

            if use_fuzzy_pid and rtt_min is not None:
                q_delay = max(0.0, measured_rtt - rtt_min)
                congested = (loss_rate > 0 or
                             q_delay > budget)
                if congested:
                    budget = max(0.5, budget * (0.5 if loss_rate > 0.3 else 0.8))
                else:
                    budget = min(20.0, budget + 0.2)
                t_rtt = rtt_min + budget
                adj   = pid_ctrl.compute(t_rtt, measured_rtt, dt)
                current_rate = max(10.0, min(500.0, current_rate + adj))
                set_switch_meter_rate(current_rate)
            # fixed-rate: do nothing — meter stays at fixed_rate_pps

            trace.append({
                "t":    round(now - start_time, 2),
                "rate": round(current_rate, 2),
                "rtt":  round(measured_rtt, 2),
                "loss": round(loss_rate * 100, 2),
            })

    ctrl = threading.Thread(target=control_loop)
    ctrl.daemon = True
    ctrl.start()

    # ── Run probes ────────────────────────────────────────────────────────────
    start_time = time.time()
    h1.cmd(f"bash {script_file}")
    elapsed = time.time() - start_time

    monitor_running = False
    ctrl_running    = False
    mon.join()

    # Collect discovered addresses
    active = set()
    if os.path.exists(results_file):
        with open(results_file) as f:
            active = {l.strip() for l in f if l.strip()}

    return active, elapsed, trace


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--hosts",        type=int,   default=50)
    parser.add_argument("--active-ratio", type=float, default=0.7)
    parser.add_argument("--fixed-rate",   type=int,   default=50,
                        help="PPS for the fixed-rate (no-PID) run")
    parser.add_argument("--target-rtt",   type=float, default=7.0)
    args = parser.parse_args()

    from mininet.log import setLogLevel
    setLogLevel("warning")

    results = {}

    for mode in ["fixed", "fuzzy"]:
        print(f"\n{'='*60}")
        print(f"  Running: {'Fixed-Rate (no PID)' if mode=='fixed' else 'FuzzyPID'}")
        print(f"{'='*60}")

        net, hosts, active_addrs = create_p4_network(
            num_hosts=args.hosts, active_ratio=args.active_ratio)
        h1, h2 = hosts[0], hosts[1]

        target_addrs = [f"2001:db8:1::{i}" for i in range(2, args.hosts + 1)]
        ground_truth = set(active_addrs) - {h1.ipv6}

        discovered, elapsed, trace = run_prober_with_trace(
            h1, h2, target_addrs,
            use_fuzzy_pid=(mode == "fuzzy"),
            fixed_rate_pps=args.fixed_rate,
            target_rtt_ms=args.target_rtt,
        )

        tp   = discovered & ground_truth
        fp   = discovered - ground_truth
        hit  = len(tp) / len(ground_truth) * 100 if ground_truth else 0
        loss = 100 - hit

        results[mode] = {
            "mode":        mode,
            "hosts":       args.hosts,
            "active":      len(ground_truth),
            "discovered":  len(tp),
            "hit_rate":    round(hit, 2),
            "false_pos":   len(fp),
            "elapsed":     round(elapsed, 2),
            "trace":       trace,
        }

        print(f"  Hit rate : {hit:.1f}%")
        print(f"  Elapsed  : {elapsed:.1f}s")
        print(f"  False +  : {len(fp)}")

        net.stop()
        time.sleep(3)   # let BMv2 clean up before next run

    os.makedirs("outputs", exist_ok=True)
    out_path = "outputs/comparison_pid.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved → {out_path}")
