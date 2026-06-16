# =============================================================================
# test_probe.py
# =============================================================================
# Quick Phase B sanity check — single experiment with 10 hosts.
# For full scale evaluation across multiple configs, use discovery_eval.py.
#
# USAGE:
#   sudo python3 scripts/test_probe.py
# =============================================================================

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from topology import create_network
from probing  import probe_all_from_host
from mininet.log import setLogLevel


def run_phase_b_test():

    print("=" * 55)
    print("6Map — Phase B Quick Test (10 hosts, 80% active)")
    print("=" * 55)

    net, hosts, active_addrs, inactive_addrs = create_network(
        num_hosts=10,
        active_ratio=0.8,
        enable_cli=False
    )

    try:
        # All addresses (active + inactive) are probe targets
        all_targets = active_addrs + inactive_addrs

        print(f"\nTarget breakdown:")
        print(f"  Active   (should respond) : {len(active_addrs)}")
        print(f"  Inactive (should be silent): {len(inactive_addrs)}")
        print(f"  Total targets             : {len(all_targets)}")

        prober = hosts[0]
        print(f"\nProbing from: {prober.name} ({prober.ipv6})")

        discovered = probe_all_from_host(
            mininet_host=prober,
            target_addresses=all_targets,
            timeout=2,
            rate_limit=0.05
        )

        discovered_set = set(discovered)
        active_set     = set(active_addrs)
        inactive_set   = set(inactive_addrs)

        true_positives  = discovered_set & active_set
        false_positives = discovered_set & inactive_set
        false_negatives = active_set - discovered_set

        print("\n" + "=" * 55)
        print("PHASE B TEST RESULTS")
        print("=" * 55)

        print(f"\nDiscovered ({len(discovered_set)}):")
        for addr in sorted(discovered_set):
            tag = "✓ ACTIVE" if addr in active_set else "✗ UNEXPECTED"
            print(f"  {addr}  [{tag}]")

        if false_negatives:
            print(f"\nMissed active hosts ({len(false_negatives)}):")
            for addr in sorted(false_negatives):
                print(f"  {addr}")

        print(f"\nMetrics:")
        print(f"  Total probed    : {len(all_targets)}")
        print(f"  True positives  : {len(true_positives)}/{len(active_addrs)}")
        print(f"  False positives : {len(false_positives)}")
        print(f"  False negatives : {len(false_negatives)}")

        hit_rate  = len(true_positives) / len(active_set) * 100 if active_set else 0
        precision = len(true_positives) / len(discovered_set) * 100 if discovered_set else 0
        print(f"  Hit rate        : {hit_rate:.1f}%")
        print(f"  Precision       : {precision:.1f}%")

        print("=" * 55)

    finally:
        print("\n*** Stopping network")
        net.stop()
        print("*** Done")


if __name__ == "__main__":
    setLogLevel('warning')
    run_phase_b_test()
