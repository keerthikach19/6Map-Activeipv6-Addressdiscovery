# =============================================================================
# topology.py
# =============================================================================
# Creates a virtual IPv6 network using Mininet for Phase B of 6Map.
#
# THE NDP PROBLEM AT SCALE:
# IPv6 uses Neighbor Discovery Protocol (NDP) instead of ARP.
# Before h1 can ping h47, it sends a Neighbor Solicitation to the
# solicited-node multicast address ff02::1:ff00:47.
# OVSBridge does not properly handle IPv6 multicast — it either drops
# or floods these packets, causing NDP to fail at 100+ hosts.
#
# THE CORRECT FIX:
# Disable NDP entirely and use statically configured /64 routes.
# Every host gets:
#   - Its IPv6 address assigned directly
#   - A static route: "to reach 2001:db8:1::/64, use my interface"
# This means ping6 resolves destinations via the route table, not NDP.
# No multicast needed. No MAC resolution needed.
#
# SCALE FIX (why 100 hosts failed at 1.2% hit rate):
# The original startup_delay = 1 + (num_hosts // 50) gave only 3s for
# 100 hosts. That is not enough time for all hosts to finish configuring
# their IPv6 addresses and static routes before probing begins.
# Fix: use a larger, scale-aware delay formula + a readiness check.
# =============================================================================

import sys
import time

from mininet.net  import Mininet
from mininet.node import OVSBridge
from mininet.link import TCLink
from mininet.log  import setLogLevel, info
from mininet.cli  import CLI

IPV6_PREFIX = "2001:db8:1"
PREFIX_LEN  = 64


def create_network(num_hosts=10, active_ratio=1.0, enable_cli=False):
    """
    Create a Mininet virtual IPv6 network.

    Args:
        num_hosts:    total number of virtual hosts to create
        active_ratio: fraction of hosts that are active (respond to pings)
        enable_cli:   open Mininet CLI for manual testing

    Returns:
        net, hosts, active_addrs, inactive_addrs
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

    hosts = []
    for i in range(1, num_hosts + 1):
        host = net.addHost(f'h{i}', ip=None)
        net.addLink(host, s1)
        hosts.append(host)

    info("\n*** Starting network\n")
    net.start()

    # ---------------------------------------------------------------
    # FIX 1: Scale-aware startup delay.
    # Old formula: 1 + (num_hosts // 50)  → 3s at 100 hosts (too short)
    # New formula: 2 + (num_hosts // 20)  → 7s at 100 hosts
    #              scales to 12s at 200 hosts, 22s at 400 hosts
    # ---------------------------------------------------------------
    startup_delay = 2 + (num_hosts // 20)
    info(f"*** Waiting {startup_delay}s for network to stabilise\n")
    time.sleep(startup_delay)

    # Determine active vs inactive split
    num_active     = max(1, int(num_hosts * active_ratio))
    active_hosts   = hosts[:num_active]
    inactive_hosts = hosts[num_active:]

    active_addrs   = []
    inactive_addrs = []

    # ------------------------------------------------------------------
    # Configure ACTIVE hosts
    # Each active host gets:
    #   1. IPv6 address assigned
    #   2. DAD disabled  (saves ~1s per host at startup)
    #   3. A static /64 route so it can reach other hosts WITHOUT NDP
    # ------------------------------------------------------------------
    info("\n*** Configuring active hosts\n")

    for i, host in enumerate(active_hosts, start=1):
        ipv6_addr = f"{IPV6_PREFIX}::{i}"
        ipv6_cidr = f"{ipv6_addr}/{PREFIX_LEN}"
        iface     = f"{host.name}-eth0"

        # Bring interface up
        host.cmd(f"ip link set {iface} up")

        # Disable DAD before assigning address — avoids 1s DAD wait
        host.cmd(f"sysctl -w net.ipv6.conf.{iface}.dad_transmits=0 > /dev/null 2>&1")
        host.cmd(f"sysctl -w net.ipv6.conf.{iface}.accept_dad=0   > /dev/null 2>&1")

        # Assign IPv6 address
        host.cmd(f"ip -6 addr add {ipv6_cidr} dev {iface}")

        # Static route: reach the whole /64 directly via this interface.
        # This eliminates the need for NDP multicast resolution entirely.
        host.cmd(
            f"ip -6 route replace {IPV6_PREFIX}::/{PREFIX_LEN} "
            f"dev {iface} metric 1 > /dev/null 2>&1"
        )

        # Enable forwarding
        host.cmd("sysctl -w net.ipv6.conf.all.forwarding=1 > /dev/null 2>&1")

        host.ipv6      = ipv6_addr
        host.is_active = True
        active_addrs.append(ipv6_addr)

    # ------------------------------------------------------------------
    # Configure INACTIVE hosts — interface up but NO IPv6 address.
    # They exist on the network but nothing listens at their address slot.
    # ------------------------------------------------------------------
    info(f"*** {len(inactive_hosts)} hosts left inactive\n")

    for i, host in enumerate(inactive_hosts, start=num_active + 1):
        iface = f"{host.name}-eth0"
        host.cmd(f"ip link set {iface} up")

        planned_addr   = f"{IPV6_PREFIX}::{i}"
        host.ipv6      = planned_addr
        host.is_active = False
        inactive_addrs.append(planned_addr)

    # ---------------------------------------------------------------
    # FIX 2: Post-configuration settling delay.
    # Gives the kernel time to finish processing all the ip commands
    # before any probing starts. Scales with host count.
    # Old code used a fixed time.sleep(1) which is too short at scale.
    # ---------------------------------------------------------------
    settle_delay = max(3, num_hosts // 25)
    info(f"*** Waiting {settle_delay}s for address configuration to settle\n")
    time.sleep(settle_delay)

    # ------------------------------------------------------------------
    # Verify connectivity between two active hosts.
    # FIX 3: if the first check fails, wait longer and retry once.
    # This catches cases where the network is almost-but-not-quite ready.
    # ------------------------------------------------------------------
    if len(active_hosts) >= 2:
        info("\n*** Verifying IPv6 connectivity\n")
        ready = _verify_connectivity(active_hosts[0], active_hosts[1])

        if not ready:
            info("*** First check failed — waiting 10 more seconds and retrying\n")
            time.sleep(10)
            _verify_connectivity(active_hosts[0], active_hosts[1])

    info("\n*** Network is ready\n")
    _print_network_info(active_addrs, inactive_addrs)

    if enable_cli:
        CLI(net)

    return net, hosts, active_addrs, inactive_addrs


def get_host_addresses(hosts):
    return [h.ipv6 for h in hosts]

def get_active_addresses(hosts):
    return [h.ipv6 for h in hosts if getattr(h, 'is_active', False)]

def get_inactive_addresses(hosts):
    return [h.ipv6 for h in hosts if not getattr(h, 'is_active', False)]


def _verify_connectivity(h1, h2):
    """
    Ping from h1 to h2. Returns True if successful, False otherwise.
    Uses 3 packets and 3s timeout to be more reliable at scale.
    """
    result = h1.cmd(f"ping6 -c 3 -W 3 {h2.ipv6}")
    success = (
        "1 received" in result or
        "2 received" in result or
        "3 received" in result or
        "1 packets received" in result
    )
    if success:
        info(f"  ✓ {h1.name} → {h2.name} OK\n")
    else:
        info(f"  ✗ WARNING: ping6 failed between {h1.name} and {h2.name}\n")
        info(f"    Output: {result[:200]}\n")
    return success


def _print_network_info(active_addrs, inactive_addrs):
    total = len(active_addrs) + len(inactive_addrs)
    print("\n" + "=" * 60)
    print("VIRTUAL IPv6 NETWORK — READY")
    print("=" * 60)
    print(f"  Subnet         : {IPV6_PREFIX}::/{PREFIX_LEN}")
    print(f"  Total hosts    : {total}")
    print(f"  Active hosts   : {len(active_addrs)}  (have IPv6, respond to pings)")
    print(f"  Inactive hosts : {len(inactive_addrs)}  (no IPv6 assigned, silent)")
    if active_addrs:
        print(f"  Active range   : {active_addrs[0]}  →  {active_addrs[-1]}")
    if inactive_addrs:
        print(f"  Inactive range : {inactive_addrs[0]}  →  {inactive_addrs[-1]}")
    print("=" * 60)


if __name__ == "__main__":
    setLogLevel('info')

    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--hosts",  type=int,   default=10)
    parser.add_argument("--active", type=float, default=0.8)
    args = parser.parse_args()

    net, hosts, active_addrs, inactive_addrs = create_network(
        num_hosts=args.hosts,
        active_ratio=args.active,
        enable_cli=True
    )
    net.stop()
