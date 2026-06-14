# =============================================================================
# topology.py
# =============================================================================
# Creates a virtual IPv6 network using Mininet for Phase B of 6Map simulation.
#
# WHAT THIS FILE DOES:
# 1. Creates a virtual switch (OVSBridge - works without a controller)
# 2. Creates N virtual hosts connected to the switch
# 3. Assigns IPv6 addresses to each host (2001:db8:1::1, ::2, ::3 ...)
# 4. Enables IPv6 forwarding on all hosts
# 5. Sets up routing so hosts can reach each other
# 6. Verifies connectivity with a ping test
# 7. Returns the network and host list for use by other scripts
#
# NETWORK LAYOUT:
#
#   h1 (2001:db8:1::1) ──┐
#   h2 (2001:db8:1::2) ──┤
#   h3 (2001:db8:1::3) ──┤── s1 (OVSBridge switch)
#   ...                  ┤
#   hN (2001:db8:1::N) ──┘
#
# All hosts are on the same /64 subnet: 2001:db8:1::/64
# They can all reach each other directly through s1.
#
# USAGE:
#   sudo python3 scripts/topology.py
# =============================================================================

import sys
import time

# Mininet imports
from mininet.net     import Mininet
from mininet.node    import OVSBridge   # OVSBridge works WITHOUT a controller
from mininet.link    import TCLink      # TCLink allows setting link properties
from mininet.log     import setLogLevel, info, error
from mininet.cli     import CLI


# =============================================================================
# CONFIGURATION
# =============================================================================

# Base IPv6 prefix for all virtual hosts
# 2001:db8::/32 is the official "documentation" range — safe to use in testing
IPV6_PREFIX = "2001:db8:1"

# Subnet prefix length — /64 is standard for IPv6 LANs
PREFIX_LEN = 64


# =============================================================================
# NETWORK CREATION
# =============================================================================

def create_network(num_hosts=10, enable_cli=False):
    """
    Create a Mininet virtual IPv6 network.

    HOW IT WORKS:
    - OVSBridge is used as the switch instead of OVSSwitch.
      OVSSwitch requires an OpenFlow controller to forward packets.
      OVSBridge acts like a simple Layer 2 Ethernet bridge — it forwards
      packets based on MAC addresses without needing a controller.
      This is perfect for our use case.

    - Each host gets:
      * A virtual ethernet interface (h1-eth0, h2-eth0, etc.)
      * An IPv6 address in the 2001:db8:1::/64 range
      * IPv6 forwarding enabled
      * A default route through the switch

    INPUT:
        num_hosts  = how many virtual hosts to create (default 10)
        enable_cli = if True, opens Mininet CLI for manual testing

    OUTPUT:
        net   = the running Mininet network object
        hosts = list of host objects
    """

    info("\n*** Setting up IPv6 Mininet network\n")

    # ------------------------------------------------------------------
    # Create the Mininet network object
    # controller=None  → no OpenFlow controller needed (OVSBridge handles it)
    # switch=OVSBridge → simple bridge, forwards by MAC address
    # link=TCLink      → allows us to set bandwidth/delay on links later
    # ------------------------------------------------------------------
    net = Mininet(
        controller=None,
        switch=OVSBridge,
        link=TCLink,
        autoSetMacs=True    # automatically assign unique MAC addresses
    )

    # ------------------------------------------------------------------
    # Create the switch
    # This is the central device all hosts connect to
    # ------------------------------------------------------------------
    info("*** Creating switch s1\n")
    s1 = net.addSwitch('s1')

    # ------------------------------------------------------------------
    # Create hosts and connect them to the switch
    # ------------------------------------------------------------------
    info(f"*** Creating {num_hosts} hosts\n")
    hosts = []

    for i in range(1, num_hosts + 1):
        # Create host with a name like h1, h2, h3...
        # ip='0.0.0.0' disables automatic IPv4 assignment
        # we handle IPv6 ourselves below
        host = net.addHost(
            f'h{i}',
            ip=None     # disable automatic IPv4 — we only use IPv6
        )

        # Connect this host to the switch with a virtual cable (veth pair)
        net.addLink(host, s1)

        hosts.append(host)
        info(f"  Created h{i} and connected to s1\n")

    # ------------------------------------------------------------------
    # Start the network
    # This actually creates all the namespaces, veth pairs, etc.
    # ------------------------------------------------------------------
    info("\n*** Starting network\n")
    net.start()

    # Small delay to let OVS initialize properly
    time.sleep(1)

    # ------------------------------------------------------------------
    # Assign IPv6 addresses to each host
    # ------------------------------------------------------------------
    info("\n*** Assigning IPv6 addresses\n")

    for i, host in enumerate(hosts, start=1):

        # Build this host's IPv6 address
        # e.g., host 1 → 2001:db8:1::1/64
        #        host 2 → 2001:db8:1::2/64
        ipv6_addr = f"{IPV6_PREFIX}::{i}"
        ipv6_cidr = f"{ipv6_addr}/{PREFIX_LEN}"

        # The interface name is always hostname-eth0
        # e.g., h1-eth0, h2-eth0
        interface = f"{host.name}-eth0"

        # Bring the interface up (it may not be up yet)
        host.cmd(f"ip link set {interface} up")

        # Assign the IPv6 address to the interface
        # 'ip -6 addr add' is the Linux command to add an IPv6 address
        result = host.cmd(f"ip -6 addr add {ipv6_cidr} dev {interface}")

        # Enable IPv6 on this interface
        # By default, Linux may have IPv6 disabled
        host.cmd(f"sysctl -w net.ipv6.conf.{interface}.disable_ipv6=0")

        # Enable IPv6 forwarding on this host
        # Without this, hosts won't forward IPv6 packets
        host.cmd("sysctl -w net.ipv6.conf.all.forwarding=1")

        # Disable IPv6 duplicate address detection (DAD)
        # DAD normally waits ~1 second before using an address
        # Disabling it makes our simulation faster
        host.cmd(f"sysctl -w net.ipv6.conf.{interface}.dad_transmits=0")
        host.cmd(f"sysctl -w net.ipv6.conf.{interface}.accept_dad=0")

        # Store the IPv6 address on the host object for easy access later
        host.ipv6 = ipv6_addr

        info(f"  {host.name}: {ipv6_cidr} on {interface}\n")

    # Small delay for addresses to become active
    time.sleep(1)

    # ------------------------------------------------------------------
    # Verify connectivity with a ping test
    # ------------------------------------------------------------------
    info("\n*** Verifying IPv6 connectivity\n")
    verify_connectivity(hosts)

    info("\n*** Network is ready\n")
    print_network_info(hosts)

    # ------------------------------------------------------------------
    # Open CLI if requested (for manual testing)
    # ------------------------------------------------------------------
    if enable_cli:
        info("\n*** Opening Mininet CLI (type 'exit' to quit)\n")
        CLI(net)

    return net, hosts


# =============================================================================
# CONNECTIVITY VERIFICATION
# =============================================================================

def verify_connectivity(hosts):
    """
    Test that hosts can ping each other.

    We ping from h1 to h2 as a basic connectivity check.
    If this works, the virtual network is correctly set up.

    HOW host.cmd() WORKS:
    host.cmd("some command") runs a shell command INSIDE the host's
    network namespace. So h1.cmd("ping6 ...") sends the ping from
    h1's perspective — using h1's interfaces and routing table.
    This is how we test connectivity between virtual hosts.
    """

    if len(hosts) < 2:
        info("  Only one host — skipping ping test\n")
        return

    h1 = hosts[0]
    h2 = hosts[1]

    h1_addr = h1.ipv6
    h2_addr = h2.ipv6

    info(f"  Testing: {h1.name} → ping6 → {h2.name} ({h2_addr})\n")

    # ping6 -c 1 = send 1 ping
    # -W 2       = wait max 2 seconds for reply
    # -I h1-eth0 = use this specific interface
    result = h1.cmd(f"ping6 -c 1 -W 2 {h2_addr}")

    if "1 received" in result or "1 packets received" in result:
        info(f"  ✓ Connectivity verified: {h1.name} can reach {h2.name}\n")
    else:
        info(f"  ✗ WARNING: ping6 failed between {h1.name} and {h2.name}\n")
        info(f"    Output: {result}\n")
        info("    This may be OK — DAD suppression sometimes needs a moment\n")


# =============================================================================
# PRINT NETWORK INFORMATION
# =============================================================================

def print_network_info(hosts):
    """
    Print a clear summary of the virtual network we created.
    This is shown every time the network starts.
    """
    print("\n" + "="*55)
    print("VIRTUAL IPv6 NETWORK — READY")
    print("="*55)
    print(f"  Subnet  : {IPV6_PREFIX}::/{PREFIX_LEN}")
    print(f"  Hosts   : {len(hosts)}")
    print()
    print(f"  {'Host':<8} {'IPv6 Address':<30} {'Interface'}")
    print(f"  {'-'*8} {'-'*30} {'-'*15}")
    for host in hosts:
        iface = f"{host.name}-eth0"
        print(f"  {host.name:<8} {host.ipv6:<30} {iface}")
    print("="*55)
    print()
    print("  These addresses are your SEEDS for Phase A clustering.")
    print("  The probing module will probe these virtual hosts.")
    print("="*55)


# =============================================================================
# HELPER: Get list of all host IPv6 addresses
# =============================================================================

def get_host_addresses(hosts):
    """
    Return a list of all host IPv6 addresses (without prefix length).
    Used by probing.py to know what addresses exist in the network.

    OUTPUT: ['2001:db8:1::1', '2001:db8:1::2', ..., '2001:db8:1::10']
    """
    return [host.ipv6 for host in hosts]


# =============================================================================
# MAIN — runs when you execute: sudo python3 scripts/topology.py
# =============================================================================

if __name__ == "__main__":

    # Set Mininet log level
    # 'info' shows useful messages without being too verbose
    setLogLevel('info')

    print("="*55)
    print("6Map Phase B — Virtual IPv6 Network")
    print("="*55)

    # Create the network with 10 hosts and open CLI for manual testing
    net, hosts = create_network(num_hosts=10, enable_cli=True)

    # When CLI exits (user types 'exit'), stop the network cleanly
    net.stop()
    info("\n*** Network stopped\n")
