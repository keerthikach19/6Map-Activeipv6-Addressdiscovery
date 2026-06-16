# =============================================================================
# test_probe.py
# =============================================================================
# Quick Phase B sanity check — single experiment with 10 hosts.
# For full scale evaluation across multiple configs, use discovery_eval.py.
#
# FIXES vs original:
#   - Uses timeout=4 instead of 2 (matches scale fix in probing.py)
#   - Added pre-probe readiness check before mass probing
#   - Excludes prober's own address from targets (same as discovery_eval.py)
#
# USAGE:
#   sudo python3 scripts/test_probe.py
#   sudo python3 scripts/test_probe.py --hosts 100 --active 0.8
# =============================================================================

import sys
import os
import argparse
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from topology import create_network
from probing  import probe_all_from_host, pre_probe_check
from mininet.log import setLogLevel


def run_phase_b_test(num_hosts=10, active_ratio=0.8, timeout=4):

    print("=" * 60)
    print(f"6Map — Phase B Quick Test ({num_hosts} hosts, {active_ratio*100:.0f}% active)")
    print("=" * 60)

    net, hosts, active_addrs, inactive_addrs = create_network(
        num_hosts=num_hosts,
        active_ratio=active_ratio,
        enable_cli=False
    )

    try:
        prober      = hosts[0]
        prober_addr = prober.ipv6

        # Exclude prober's own address — pinging yourself skews results
        all_targets = [a for a in active_addrs + inactive_addrs
                       if a != prober_addr]

        print(f"\nTarget breakdown:")
        print(f"  Active   (should respond) : {len(active_addrs)}")
        print(f"  Inactive (should be silent): {len(inactive_addrs)}")
        print(f"  Total targets (excl. self) : {len(all_targets)}")
        print(f"\nProbing from: {prober.name} ({prober_addr})")

        # ----------------------------------------------------------------
        # Readiness check — same pattern as discovery_eval.py
        # ----------------------------------------------------------------
        known_active_targets = [a for a in active_addrs if a != prober_addr]
        sample = known_active_targets[:3]

        ready = False
        for attempt in range(1, 4):
            ready = pre_probe_check(prober, sample, timeout=timeout)
            if ready:
                break
            wait = 10 * attempt
            print(f"Network not ready (attempt {attempt}/3). Waiting {wait}s...")
            time.sleep(wait)

        if not ready:
            print("WARNING: Readiness check failed. Proceeding anyway.")
        # ----------------------------------------------------------------

        discovered = probe_all_from_host(
            mininet_host=prober,
            target_addresses=all_targets,
            timeout=timeout,
            rate_limit=0.05
        )

        # Add prober back as auto-discovered (it is active)
        if prober_addr in active_addrs:
            discovered = list(set(discovered) | {prober_addr})

        discovered_set = set(discovered)
        active_set     = set(active_addrs)
        inactive_set   = set(inactive_addrs)

        true_positives  = discovered_set & active_set
        false_positives = discovered_set & inactive_set
        false_negatives = active_set - discovered_set

        print("\n" + "=" * 60)
        print("PHASE B TEST RESULTS")
        print("=" * 60)

        print(f"\nDiscovered ({len(discovered_set)}):")
        for addr in sorted(discovered_set):
            tag = "✓ ACTIVE" if addr in active_set else "✗ UNEXPECTED"
            print(f"  {addr}  [{tag}]")

        if false_negatives:
            print(f"\nMissed active hosts ({len(false_negatives)}):")
            for addr in sorted(false_negatives):
                print(f"  {addr}")

        hit_rate  = len(true_positives) / len(active_set) * 100 if active_set else 0
        precision = len(true_positives) / len(discovered_set) * 100 if discovered_set else 0

        print(f"\nMetrics:")
        print(f"  Total probed    : {len(all_targets)} + 1 (prober self)")
        print(f"  True positives  : {len(true_positives)}/{len(active_addrs)}")
        print(f"  False positives : {len(false_positives)}")
        print(f"  False negatives : {len(false_negatives)}")
        print(f"  Hit rate        : {hit_rate:.1f}%")
        print(f"  Precision       : {precision:.1f}%")

        print("=" * 60)

    finally:
        print("\n*** Stopping network")
        net.stop()
        print("*** Done")


if __name__ == "__main__":
    setLogLevel('warning')

    parser = argparse.ArgumentParser(description="6Map Phase B Quick Test")
    parser.add_argument("--hosts",   type=int,   default=10,
                        help="Number of hosts (default 10)")
    parser.add_argument("--active",  type=float, default=0.8,
                        help="Active ratio (default 0.8)")
    parser.add_argument("--timeout", type=float, default=4.0,
                        help="Probe timeout in seconds (default 4)")
    args = parser.parse_args()

    run_phase_b_test(
        num_hosts=args.hosts,
        active_ratio=args.active,
        timeout=args.timeout
    )
