# =============================================================================
# discovery_eval.py
# =============================================================================
# Runs the full Phase B discovery evaluation:
#
#   For each scale configuration (e.g. 50, 100, 500 hosts):
#     1. Create a virtual network with active + inactive hosts
#     2. Probe all addresses from inside the network (h1 as prober)
#     3. Compare discovered set against ground truth
#     4. Record: hit rate, false positives, false negatives, probe count
#
# USAGE:
#   sudo python3 scripts/discovery_eval.py
#   sudo python3 scripts/discovery_eval.py --scales 50 100 200
#   sudo python3 scripts/discovery_eval.py --scales 100 --active 0.7
# =============================================================================

import sys
import os
import time
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from topology import create_network
from probing  import probe_all_from_host
from mininet.log import setLogLevel


# =============================================================================
# SINGLE SCALE EXPERIMENT
# =============================================================================

def run_experiment(num_hosts, active_ratio=0.8, timeout=2, rate_limit=0.05):
    """
    Run one complete discovery experiment at a given scale.

    Args:
        num_hosts:    total virtual hosts to create
        active_ratio: fraction that are active (have IPv6 + respond)
        timeout:      seconds to wait per probe
        rate_limit:   seconds between probes (controls probe rate)

    Returns:
        dict with all result metrics
    """

    print(f"\n{'='*60}")
    print(f"EXPERIMENT  |  hosts={num_hosts}  active={active_ratio*100:.0f}%")
    print(f"{'='*60}")

    net, hosts, active_addrs, inactive_addrs = create_network(
        num_hosts=num_hosts,
        active_ratio=active_ratio,
        enable_cli=False
    )

    try:
        # ----------------------------------------------------------------
        # Build probe target list:
        # active + inactive addresses — prober doesn't know which is which
        # ----------------------------------------------------------------
        all_targets = active_addrs + inactive_addrs

        print(f"\nProbe targets  : {len(all_targets)}")
        print(f"  Known active : {len(active_addrs)}")
        print(f"  Known silent : {len(inactive_addrs)}")

        prober = hosts[0]
        print(f"  Probing from : {prober.name} ({prober.ipv6})\n")

        start_time = time.time()

        discovered = probe_all_from_host(
            mininet_host=prober,
            target_addresses=all_targets,
            timeout=timeout,
            rate_limit=rate_limit
        )

        elapsed = time.time() - start_time

        # ----------------------------------------------------------------
        # Compute metrics
        # ----------------------------------------------------------------
        discovered_set = set(discovered)
        active_set     = set(active_addrs)
        inactive_set   = set(inactive_addrs)

        true_positives  = discovered_set & active_set      # found + really active
        false_positives = discovered_set & inactive_set    # found + actually silent
        false_negatives = active_set - discovered_set      # missed active hosts

        hit_rate        = len(true_positives) / len(active_set)  if active_set     else 0.0
        fp_rate         = len(false_positives) / len(inactive_set) if inactive_set else 0.0
        precision       = len(true_positives) / len(discovered_set) if discovered_set else 0.0

        result = {
            "num_hosts"       : num_hosts,
            "active_ratio"    : active_ratio,
            "num_active"      : len(active_addrs),
            "num_inactive"    : len(inactive_addrs),
            "total_probed"    : len(all_targets),
            "discovered"      : len(discovered_set),
            "true_positives"  : len(true_positives),
            "false_positives" : len(false_positives),
            "false_negatives" : len(false_negatives),
            "hit_rate_pct"    : round(hit_rate  * 100, 2),
            "fp_rate_pct"     : round(fp_rate   * 100, 2),
            "precision_pct"   : round(precision * 100, 2),
            "elapsed_sec"     : round(elapsed, 1),
            "probes_per_sec"  : round(len(all_targets) / elapsed, 1) if elapsed > 0 else 0,
        }

        _print_result(result)
        return result

    finally:
        net.stop()
        print(f"\n*** Network stopped")


# =============================================================================
# PRINT ONE RESULT
# =============================================================================

def _print_result(r):
    print(f"\n{'─'*60}")
    print(f"RESULTS  |  hosts={r['num_hosts']}  active={r['active_ratio']*100:.0f}%")
    print(f"{'─'*60}")
    print(f"  Total probed      : {r['total_probed']}")
    print(f"  Discovered active : {r['discovered']}")
    print()
    print(f"  True positives    : {r['true_positives']}  (correctly found active hosts)")
    print(f"  False positives   : {r['false_positives']}  (inactive host that appeared active)")
    print(f"  False negatives   : {r['false_negatives']}  (active hosts we missed)")
    print()
    print(f"  Hit rate          : {r['hit_rate_pct']}%   (recall — active hosts found)")
    print(f"  Precision         : {r['precision_pct']}%   (of found, how many are real)")
    print(f"  False positive rate: {r['fp_rate_pct']}%")
    print()
    print(f"  Time elapsed      : {r['elapsed_sec']}s")
    print(f"  Probe rate        : {r['probes_per_sec']} probes/sec")
    print(f"{'─'*60}")


# =============================================================================
# SUMMARY TABLE ACROSS SCALES
# =============================================================================

def print_summary_table(results):
    print(f"\n{'='*70}")
    print("SCALE EXPERIMENT SUMMARY")
    print(f"{'='*70}")
    print(f"{'Hosts':>8}  {'Active':>8}  {'Found':>8}  "
          f"{'Hit%':>8}  {'Prec%':>8}  {'FP%':>6}  {'Time(s)':>8}")
    print(f"{'─'*70}")
    for r in results:
        print(f"{r['num_hosts']:>8}  "
              f"{r['num_active']:>8}  "
              f"{r['true_positives']:>8}  "
              f"{r['hit_rate_pct']:>7.1f}%  "
              f"{r['precision_pct']:>7.1f}%  "
              f"{r['fp_rate_pct']:>5.1f}%  "
              f"{r['elapsed_sec']:>8.1f}")
    print(f"{'='*70}")

    # Save to file
    os.makedirs("outputs", exist_ok=True)
    with open("outputs/discovery_results.txt", "w") as f:
        f.write("Scale Experiment Results\n")
        f.write("=" * 70 + "\n")
        f.write(f"{'Hosts':>8}  {'Active':>8}  {'Found':>8}  "
                f"{'Hit%':>8}  {'Prec%':>8}  {'FP%':>6}  {'Time(s)':>8}\n")
        f.write("─" * 70 + "\n")
        for r in results:
            f.write(f"{r['num_hosts']:>8}  "
                    f"{r['num_active']:>8}  "
                    f"{r['true_positives']:>8}  "
                    f"{r['hit_rate_pct']:>7.1f}%  "
                    f"{r['precision_pct']:>7.1f}%  "
                    f"{r['fp_rate_pct']:>5.1f}%  "
                    f"{r['elapsed_sec']:>8.1f}\n")
    print("\nResults saved to outputs/discovery_results.txt")


# =============================================================================
# VS RANDOM BASELINE
# =============================================================================

def print_random_baseline_comparison(results):
    """
    Compare our structured probing against random scanning baseline.
    Random scanning of a /64 has essentially 0% chance of hitting anything.
    """
    print(f"\n{'='*60}")
    print("VS RANDOM SCANNING BASELINE")
    print(f"{'='*60}")
    print(f"  Subnet size (2001:db8:1::/64): 2^64 addresses")
    print(f"  = 18,446,744,073,709,551,616")
    print()
    for r in results:
        chance = r['num_active'] / (2 ** 64) * 100
        print(f"  {r['num_hosts']} hosts  →  random hit chance per probe: {chance:.2e}%")
        print(f"             structured hit rate:    {r['hit_rate_pct']:.1f}%")
        print()
    print(f"{'='*60}")


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="6Map Phase B — Discovery Evaluation")
    parser.add_argument(
        "--scales",
        type=int,
        nargs="+",
        default=[50, 100],
        help="List of host counts to test, e.g. --scales 50 100 200"
    )
    parser.add_argument(
        "--active",
        type=float,
        default=0.8,
        help="Fraction of hosts that are active (default 0.8)"
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=2.0,
        help="Probe timeout in seconds (default 2)"
    )
    parser.add_argument(
        "--rate",
        type=float,
        default=0.05,
        help="Seconds between probes — lower = faster (default 0.05)"
    )
    args = parser.parse_args()

    setLogLevel('warning')   # suppress Mininet output for cleaner results

    print("=" * 60)
    print("6Map — Phase B Discovery Evaluation")
    print("=" * 60)
    print(f"  Scale configs : {args.scales}")
    print(f"  Active ratio  : {args.active * 100:.0f}%")
    print(f"  Probe timeout : {args.timeout}s")
    print(f"  Probe rate    : 1 per {args.rate}s  ({1/args.rate:.0f} probes/sec max)")

    all_results = []

    for scale in args.scales:
        result = run_experiment(
            num_hosts=scale,
            active_ratio=args.active,
            timeout=args.timeout,
            rate_limit=args.rate
        )
        all_results.append(result)

        # Give the system a moment between experiments
        if scale != args.scales[-1]:
            print("\nPausing 3s before next experiment...")
            time.sleep(3)

    print_summary_table(all_results)
    print_random_baseline_comparison(all_results)
