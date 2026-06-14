# =============================================================================
# test_probe.py
# =============================================================================
# Phase B end-to-end test:
# Creates virtual network, probes it, measures discovery rate.
#
# THIS REPLACES the two-terminal approach.
# Everything runs in one script:
#   1. Network starts
#   2. Probing runs from inside the network
#   3. Results printed
#   4. Network stops
#
# USAGE:
#   sudo python3 scripts/test_probe.py
#
# DO NOT run from inside Mininet CLI.
# Run directly from your terminal as shown above.
# =============================================================================

import sys
import os

# Add scripts directory to path so we can import topology and probing
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from topology import create_network, get_host_addresses
from probing  import probe_all_from_host

from mininet.log import setLogLevel


def run_phase_b_test():
    """
    Complete Phase B test:
    1. Create virtual IPv6 network
    2. Probe all hosts from h1
    3. Also probe a fake address (should not respond)
    4. Print discovery statistics
    5. Stop network
    """

    print("=" * 55)
    print("6Map — Phase B End-to-End Test")
    print("=" * 55)

    # ------------------------------------------------------------------
    # Step 1: Create the virtual network
    # ------------------------------------------------------------------
    # enable_cli=False means we don't open the interactive CLI
    # The network starts, we run our test, then it stops automatically
    net, hosts = create_network(num_hosts=10, enable_cli=False)

    try:
        # ------------------------------------------------------------------
        # Step 2: Define target addresses to probe
        # ------------------------------------------------------------------
        # Get all real host addresses (these SHOULD respond)
        real_addresses = get_host_addresses(hosts)

        # Add some fake addresses (these should NOT respond)
        # These simulate addresses that are in our probe range
        # but don't have any active device behind them
        fake_addresses = [
            "2001:db8:1::99",    # not assigned to any host
            "2001:db8:1::100",   # not assigned to any host
            "2001:db8:1::999",   # not assigned to any host
        ]

        # Combine real + fake into our probe target list
        # This simulates what happens when our wildcard patterns
        # generate addresses — some will be active, some won't
        all_targets = real_addresses + fake_addresses

        print(f"\nTarget breakdown:")
        print(f"  Real hosts (should respond) : {len(real_addresses)}")
        print(f"  Fake addresses (no response): {len(fake_addresses)}")
        print(f"  Total targets               : {len(all_targets)}")

        # ------------------------------------------------------------------
        # Step 3: Choose which host to probe FROM
        # ------------------------------------------------------------------
        # We probe FROM h1 — it has full network access to all other hosts
        # probe_all_from_host() runs ping6 inside h1's namespace
        prober = hosts[0]   # h1
        print(f"\nProbing from: {prober.name} ({prober.ipv6})")

        # ------------------------------------------------------------------
        # Step 4: Run the probes
        # ------------------------------------------------------------------
        active_addresses = probe_all_from_host(
            mininet_host=prober,
            target_addresses=all_targets,
            timeout=2,        # wait 2 seconds per probe
            rate_limit=0.05   # 20 probes per second max
        )

        # ------------------------------------------------------------------
        # Step 5: Calculate and display results
        # ------------------------------------------------------------------
        print("\n" + "=" * 55)
        print("PHASE B TEST RESULTS")
        print("=" * 55)

        # How many real hosts did we find?
        found_real = [a for a in active_addresses if a in real_addresses]
        found_fake = [a for a in active_addresses if a in fake_addresses]

        print(f"\nDiscovered active addresses ({len(active_addresses)}):")
        for addr in active_addresses:
            tag = "REAL HOST" if addr in real_addresses else "UNEXPECTED"
            print(f"  {addr}  [{tag}]")

        print(f"\nMissed addresses ({len(real_addresses) - len(found_real)}):")
        for addr in real_addresses:
            if addr not in active_addresses:
                print(f"  {addr}")

        print(f"\nStatistics:")
        print(f"  Total probed         : {len(all_targets)}")
        print(f"  Active found         : {len(active_addresses)}")
        print(f"  Real hosts found     : {len(found_real)}/{len(real_addresses)}")
        print(f"  False positives      : {len(found_fake)}")
        print(f"  Hit rate (real hosts): {len(found_real)/len(real_addresses)*100:.1f}%")
        print(f"  Overall hit rate     : {len(active_addresses)/len(all_targets)*100:.1f}%")

        # Compare to random probing baseline
        # If we randomly probed the /64 subnet (2^64 addresses),
        # chance of hitting even one host = near zero.
        # Our structured probing finds all of them.
        print(f"\nVs random probing baseline:")
        print(f"  Random probe of 2001:db8:1::/64 subnet")
        print(f"  Subnet size: 2^64 = 18,446,744,073,709,551,616 addresses")
        print(f"  Chance of hitting 1 host randomly: ~0.000000000000000054%")
        print(f"  Our algorithm hit rate: {len(found_real)/len(real_addresses)*100:.1f}%")

        print("=" * 55)

    finally:
        # ------------------------------------------------------------------
        # Step 6: Always stop the network, even if an error occurred
        # ------------------------------------------------------------------
        print("\n*** Stopping network")
        net.stop()
        print("*** Done")


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":

    # Suppress most Mininet output for cleaner results display
    setLogLevel('warning')

    run_phase_b_test()
