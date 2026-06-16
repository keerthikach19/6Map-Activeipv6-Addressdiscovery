# =============================================================================
# topology.py
# =============================================================================
# Creates a virtual IPv6 network using Mininet for Phase B of 6Map simulation.
#
# NETWORK LAYOUT:
#
#   h1  (2001:db8:1::1)  ──┐
#   h2  (2001:db8:1::2)  ──┤
#   ...                    ├── s1 (OVSBridge switch)
#   hN  (2001:db8:1::N)  ──┘
#
# Supports:
#   - Configurable host count (10 → 500+)
#   - Active vs inactive host simulation (inactive hosts have no IPv6 assigned)
#   - Returns separate lists of active and inactive addresses
# =============================================================================

import sys
import time

from mininet.net  import Mininet
from mininet.node import OVSBridge
from mininet.link import TCLink
from mininet.log  import setLogLevel, info
from mininet.cli  import CLI


# =============================================================================
# CONFIGURATION
# =============================================================================

IPV6_PREFIX = "2001:db8:1"
PREFIX_LEN  = 64


# =============================================================================
# NETWORK CREATION
# =============================================================================

def create_network(num_hosts=10, active_ratio=1.0, enable_cli=False):
    """
    Create a Mininet virtual IPv6 network with configurable active/inactive hosts.

    Args:
        num_hosts:    total number of virtual hosts to create
        active_ratio: fraction of hosts that are "active" (have IPv6 + respond to pings)
                      e.g. 0.8 means 80% active, 20% inactive
                      inactive hosts exist on the network but have no IPv6 address assigned
        enable_cli:   open Mininet CLI for manual testing

    Returns:
        net             - running Mininet object
        hosts           - list of all host objects
        active_addrs    - list of IPv6 strings for active hosts
        inactive_addrs  - list of IPv6 strings that were "planned" but not assigned
    """

    info(f"\n*** Setting up IPv6 Mininet network "
         f"({num_hosts} hosts, {active_ratio*100:.0f}% active)\n")

    net = Mininet(
        controller=None,
        switch=OVSBridge,
        link=TCLink,
        autoSetMacs=True
    )

    info("*** Creating switch s1\n")
    s1 = net.addSwitch('s1')

    info(f"*** Creating {num_hosts} hosts\n")
    hosts = []

    for i in range(1, num_hosts + 1):
        host = net.addHost(f'h{i}', ip=None)
        net.addLink(host, s1)
        hosts.append(host)

    info("\n*** Starting network\n")
    net.start()

    # Larger networks need more time for OVS to initialise all ports
    startup_delay = 1 + (num_hosts // 50)   # 1s for ≤50, 2s for ≤100, 3s for ≤150 …
    time.sleep(startup_delay)

    # ------------------------------------------------------------------
    # Decide which hosts are active vs inactive
    # ------------------------------------------------------------------
    num_active     = max(1, int(num_hosts * active_ratio))
    active_hosts   = hosts[:num_active]
    inactive_hosts = hosts[num_active:]

    active_addrs   = []
    inactive_addrs = []

    info("\n*** Assigning IPv6 addresses to active hosts\n")

    for i, host in enumerate(active_hosts, start=1):
        ipv6_addr = f"{IPV6_PREFIX}::{i}"
        ipv6_cidr = f"{ipv6_addr}/{PREFIX_LEN}"
        iface     = f"{host.name}-eth0"

        host.cmd(f"ip link set {iface} up")
        host.cmd(f"ip -6 addr add {ipv6_cidr} dev {iface}")
        host.cmd(f"sysctl -w net.ipv6.conf.{iface}.disable_ipv6=0 > /dev/null 2>&1")
        host.cmd("sysctl -w net.ipv6.conf.all.forwarding=1 > /dev/null 2>&1")
        host.cmd(f"sysctl -w net.ipv6.conf.{iface}.dad_transmits=0 > /dev/null 2>&1")
        host.cmd(f"sysctl -w net.ipv6.conf.{iface}.accept_dad=0 > /dev/null 2>&1")

        host.ipv6      = ipv6_addr
        host.is_active = True
        active_addrs.append(ipv6_addr)

    info(f"*** {len(inactive_hosts)} hosts left inactive (no IPv6 assigned)\n")

    for i, host in enumerate(inactive_hosts, start=num_active + 1):
        iface = f"{host.name}-eth0"
        host.cmd(f"ip link set {iface} up")

        planned_addr   = f"{IPV6_PREFIX}::{i}"
        host.ipv6      = planned_addr
        host.is_active = False
        inactive_addrs.append(planned_addr)

    time.sleep(1)

    # ------------------------------------------------------------------
    # WARMUP: send one ping from every active host to h1 so the OVS
    # bridge learns all MAC addresses before real probing starts.
    # Without this, the first probe to each host triggers MAC learning
    # and the packet is flooded/dropped, causing false timeouts.
    # ------------------------------------------------------------------
    info("\n*** Warming up switch MAC table\n")
    _warmup_switch(active_hosts)

    # ------------------------------------------------------------------
    # Verify connectivity
    # ------------------------------------------------------------------
    if len(active_hosts) >= 2:
        info("\n*** Verifying IPv6 connectivity\n")
        _verify_connectivity(active_hosts[0], active_hosts[1])

    info("\n*** Network is ready\n")
    _print_network_info(active_addrs, inactive_addrs)

    if enable_cli:
        info("\n*** Opening Mininet CLI (type 'exit' to quit)\n")
        CLI(net)

    return net, hosts, active_addrs, inactive_addrs


# =============================================================================
# HELPERS
# =============================================================================

def get_host_addresses(hosts):
    """Return IPv6 addresses of ALL hosts (active + inactive)."""
    return [h.ipv6 for h in hosts]


def get_active_addresses(hosts):
    """Return only the addresses of active hosts."""
    return [h.ipv6 for h in hosts if getattr(h, 'is_active', False)]


def get_inactive_addresses(hosts):
    """Return the planned addresses of inactive (non-responding) hosts."""
    return [h.ipv6 for h in hosts if not getattr(h, 'is_active', False)]


def _warmup_switch(active_hosts):
    """
    Send one ping from every active host to the first host (h1) so the
    OVSBridge learns all MAC addresses before real probing begins.

    WHY THIS MATTERS:
    OVSBridge learns MAC→port mappings the first time it sees a frame from
    each host.  Until it has learned a MAC, it floods the frame to ALL ports
    (slow, noisy, can cause the first probe to time out).  By sending a cheap
    warmup ping from every host, we pre-populate the MAC table so that every
    subsequent probe is forwarded directly — not flooded.

    At 50 hosts this rarely matters; at 100+ hosts without warmup, almost
    every first probe floods and the 2-second timeout fires, giving 1% hit rate.
    """
    if not active_hosts:
        return

    anchor = active_hosts[0]   # every host pings h1 to seed the MAC table

    info(f"  Warming up MAC table: each host pings {anchor.name} ({anchor.ipv6})\n")

    for host in active_hosts[1:]:
        # -c 1 = one ping, -W 1 = 1s timeout, we don't care about success
        host.cmd(f"ping6 -c 1 -W 1 {anchor.ipv6} > /dev/null 2>&1")

    # Also have h1 ping h2 so h1's MAC is known going the other direction
    if len(active_hosts) >= 2:
        anchor.cmd(f"ping6 -c 1 -W 1 {active_hosts[1].ipv6} > /dev/null 2>&1")

    # Small pause for the switch to process all the learned MACs
    time.sleep(1)
    info("  MAC table warmup complete\n")


def _verify_connectivity(h1, h2):
    result = h1.cmd(f"ping6 -c 1 -W 2 {h2.ipv6}")
    if "1 received" in result or "1 packets received" in result:
        info(f"  ✓ {h1.name} → {h2.name} OK\n")
    else:
        info(f"  ✗ WARNING: ping6 failed between {h1.name} and {h2.name}\n")
        info("    This may resolve in a moment — DAD sometimes needs time\n")


def _print_network_info(active_addrs, inactive_addrs):
    total = len(active_addrs) + len(inactive_addrs)
    print("\n" + "=" * 60)
    print("VIRTUAL IPv6 NETWORK — READY")
    print("=" * 60)
    print(f"  Subnet         : {IPV6_PREFIX}::/{PREFIX_LEN}")
    print(f"  Total hosts    : {total}")
    print(f"  Active hosts   : {len(active_addrs)}  (have IPv6, respond to pings)")
    print(f"  Inactive hosts : {len(inactive_addrs)}  (no IPv6 assigned, silent)")
    print()
    if active_addrs:
        print(f"  Active range   : {active_addrs[0]}  →  {active_addrs[-1]}")
    if inactive_addrs:
        print(f"  Inactive range : {inactive_addrs[0]}  →  {inactive_addrs[-1]}")
    print("=" * 60)


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    setLogLevel('info')

    import argparse
    parser = argparse.ArgumentParser(description="6Map virtual IPv6 network")
    parser.add_argument("--hosts",  type=int,   default=10,  help="Number of hosts")
    parser.add_argument("--active", type=float, default=0.8, help="Active ratio (0.0-1.0)")
    args = parser.parse_args()

    print("=" * 60)
    print("6Map Phase B — Virtual IPv6 Network")
    print("=" * 60)

    net, hosts, active_addrs, inactive_addrs = create_network(
        num_hosts=args.hosts,
        active_ratio=args.active,
        enable_cli=True
    )

    net.stop()
    info("\n*** Network stopped\n")
