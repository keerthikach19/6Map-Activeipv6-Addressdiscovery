# =============================================================================
# probing.py
# =============================================================================
# Sends IPv6 probe packets to target addresses and records which ones respond.
#
# WHAT THIS FILE DOES:
# 1. Takes a list of IPv6 target addresses
# 2. Sends an ICMPv6 Echo Request (ping6) to each one using Scapy
# 3. Waits for a reply
# 4. Records the address as ACTIVE if it replied, INACTIVE if it didn't
# 5. Returns the list of active addresses with timing statistics
#
# WHY WE USE SCAPY INSTEAD OF ping6:
# Scapy gives us complete control over every packet field.
# It lets us specify exactly which network interface to send on,
# craft custom packets, and process replies programmatically.
# ping6 is a command-line tool — harder to automate and control.
#
# THE INTERFACE PROBLEM (why this is tricky):
# Our virtual hosts exist inside Linux network namespaces.
# Scapy runs in YOUR namespace (the main system).
# To reach virtual hosts, Scapy must send packets on the
# virtual interface that connects YOUR namespace to the switch.
#
# In Mininet, when you create a link between h1 and s1,
# it creates a veth pair. One end goes into h1's namespace,
# the other end stays in the ROOT namespace with a name like
# 's1-eth1'. Scapy can use this root-namespace interface
# to send packets into the virtual network.
#
# USAGE (from within topology.py or standalone):
#   from probing import probe_addresses
#   active = probe_addresses(addresses, interface="s1-eth1")
# =============================================================================

import time
import subprocess
from scapy.all import (
    IPv6,
    ICMPv6EchoRequest,
    ICMPv6EchoReply,
    sr1,
    conf,
    get_if_list
)


# =============================================================================
# CONFIGURATION
# =============================================================================

# Default timeout in seconds to wait for a reply to each probe
DEFAULT_TIMEOUT = 2

# Default interface to send probes on
# This is the switch-side interface in the ROOT namespace
# s1-eth1 connects the switch to h1, but we send TO the switch
# and let it forward to the correct host
# We use the loopback or a specific interface — explained below
DEFAULT_INTERFACE = None   # will be auto-detected


# =============================================================================
# INTERFACE DETECTION
# =============================================================================

def find_mininet_interface():
    """
    Find the correct network interface to send probes through.

    When Mininet runs, it creates virtual interfaces in the root namespace.
    These interfaces connect your main system to the virtual switch.

    The interface we want is typically named something like:
    - s1-eth1, s1-eth2 (switch-side of veth pairs)

    We look for any interface that starts with 's1-' or contains 'eth'
    and is part of the Mininet virtual network.

    OUTPUT: interface name string like 's1-eth1', or None if not found
    """
    try:
        interfaces = get_if_list()
        # Look for switch interfaces created by Mininet
        for iface in interfaces:
            if iface.startswith('s1-') or iface.startswith('s2-'):
                return iface
        return None
    except Exception:
        return None


def find_host_interface(host_name):
    """
    Find the interface name for a specific Mininet host in the ROOT namespace.

    When Mininet creates a link between h1 and s1, it creates two veth interfaces:
    - h1-eth0 : lives inside h1's network namespace
    - s1-eth1 : lives in the ROOT namespace (accessible by Scapy)

    To probe FROM the perspective of h1, we run Scapy inside h1's namespace.
    But to probe FROM the root, we use the s1-ethX interface.

    This function finds which s1-ethX interface connects to a given host.

    INPUT:  host_name like 'h1'
    OUTPUT: interface name like 's1-eth1'
    """
    try:
        # Use 'ip link show' to list all interfaces
        result = subprocess.run(
            ['ip', 'link', 'show'],
            capture_output=True, text=True
        )
        interfaces = get_if_list()
        # Return first switch interface found
        for iface in interfaces:
            if iface.startswith('s1-'):
                return iface
        return None
    except Exception:
        return None


# =============================================================================
# SINGLE ADDRESS PROBE
# =============================================================================

def probe_address(address, interface=None, timeout=DEFAULT_TIMEOUT):
    """
    Send one ICMPv6 Echo Request to a single IPv6 address.
    Return True if the host responds, False if it doesn't.

    HOW IT WORKS:
    1. Build an ICMPv6 Echo Request packet using Scapy
       IPv6(dst=address) sets the destination address
       ICMPv6EchoRequest() is the "ping" message

    2. sr1() sends the packet and waits for ONE reply
       sr = send and receive
       1  = receive only 1 packet (the first reply)

    3. If we got a reply AND it's an ICMPv6EchoReply → host is active
       If timeout expired with no reply → host is inactive

    THE INTERFACE ISSUE:
    We must specify which network interface to send the packet on.
    If interface=None, Scapy uses the system's default route interface
    (your real WiFi/ethernet), which CANNOT reach Mininet hosts.
    We must specify the virtual interface explicitly.

    INPUT:
        address   = IPv6 address string like '2001:db8:1::1'
        interface = network interface name like 's1-eth1'
        timeout   = seconds to wait for reply

    OUTPUT:
        True  if host responded
        False if no response
    """
    try:
        # Build the probe packet
        # IPv6()              = IPv6 header
        # dst=address         = destination address to probe
        # ICMPv6EchoRequest() = the ping message (type 128)
        packet = IPv6(dst=address) / ICMPv6EchoRequest()

        # Send the packet and wait for a reply
        # iface   = which interface to send on
        # timeout = how long to wait
        # verbose = False means don't print packet details to terminal
        if interface:
            reply = sr1(
                packet,
                iface=interface,
                timeout=timeout,
                verbose=False
            )
        else:
            reply = sr1(
                packet,
                timeout=timeout,
                verbose=False
            )

        # Check if we got a valid reply
        if reply is None:
            return False   # no response = inactive

        # Check the reply is actually an ICMPv6 Echo Reply (type 129)
        # and not some other packet type
        if ICMPv6EchoReply in reply:
            return True    # got a proper ping reply = active

        return False

    except Exception as e:
        # Any error (permission denied, interface not found, etc.)
        # counts as no response
        return False


# =============================================================================
# PROBE A LIST OF ADDRESSES
# =============================================================================

def probe_addresses(addresses, interface=None, timeout=DEFAULT_TIMEOUT,
                    rate_limit=0.1):
    """
    Send probes to a list of IPv6 addresses and return the active ones.

    Goes through the list one by one, probes each address,
    and collects the results.

    INPUT:
        addresses  = list of IPv6 address strings
        interface  = network interface to send probes on
        timeout    = seconds to wait per probe
        rate_limit = seconds to wait BETWEEN probes (prevents flooding)
                     0.1 = 10 probes per second maximum

    OUTPUT:
        active = list of IPv6 address strings that responded
    """

    if not addresses:
        print("No addresses to probe.")
        return []

    # Auto-detect interface if not provided
    if interface is None:
        interface = find_mininet_interface()
        if interface:
            print(f"Auto-detected interface: {interface}")
        else:
            print("WARNING: Could not auto-detect Mininet interface.")
            print("Probing may not work correctly.")
            print("Try specifying interface manually.")

    print(f"\nProbing {len(addresses)} addresses on interface '{interface}'")
    print("-" * 50)

    active  = []      # addresses that responded
    total   = len(addresses)
    start_time = time.time()

    for idx, addr in enumerate(addresses, 1):

        # Show progress
        print(f"[{idx:3d}/{total}] Probing {addr} ... ", end='', flush=True)

        # Send the probe
        is_active = probe_address(addr, interface=interface, timeout=timeout)

        if is_active:
            active.append(addr)
            print("ACTIVE ✓")
        else:
            print("no response")

        # Rate limiting — wait between probes
        # This prevents us from flooding the virtual network
        if idx < total:  # don't wait after the last probe
            time.sleep(rate_limit)

    # Calculate and show statistics
    elapsed = time.time() - start_time
    print("-" * 50)
    print(f"Probing complete in {elapsed:.1f} seconds")
    print(f"Active   : {len(active)}/{total}")
    print(f"Inactive : {total - len(active)}/{total}")
    if total > 0:
        print(f"Hit rate : {len(active)/total*100:.1f}%")

    return active


# =============================================================================
# PROBE FROM INSIDE A MININET HOST (Alternative approach)
# =============================================================================

def probe_from_host(mininet_host, target_address, timeout=DEFAULT_TIMEOUT):
    """
    Send a probe FROM INSIDE a Mininet host's namespace.

    This is an alternative to using Scapy from the root namespace.
    Instead, we run a ping6 command inside the host's own namespace.

    This is simpler and avoids interface detection issues.
    The downside is less control over the packet format.

    HOW host.cmd() WORKS:
    host.cmd("command") runs the command inside the host's network namespace.
    So h1.cmd("ping6 2001:db8:1::2") sends the ping FROM h1's perspective,
    using h1's interface and routing table.

    INPUT:
        mininet_host   = Mininet host object (e.g., h1)
        target_address = IPv6 address string to probe
        timeout        = seconds to wait

    OUTPUT:
        True  if target responded
        False if no response
    """
    # Run ping6 from inside the host's namespace
    # -c 1 = send only 1 ping
    # -W N = wait N seconds for reply
    result = mininet_host.cmd(
        f"ping6 -c 1 -W {timeout} {target_address} 2>&1"
    )

    # Check if the ping succeeded
    return "1 received" in result or "1 packets received" in result


def probe_all_from_host(mininet_host, target_addresses,
                        timeout=DEFAULT_TIMEOUT, rate_limit=0.05):
    """
    Probe a list of addresses FROM INSIDE a specific Mininet host.

    This is the RECOMMENDED approach for Phase B because:
    - No interface detection needed
    - Works reliably inside Mininet namespaces
    - host.cmd() handles namespace isolation automatically

    INPUT:
        mininet_host     = Mininet host object to probe from (e.g., h1)
        target_addresses = list of IPv6 address strings to probe
        timeout          = seconds to wait per probe
        rate_limit       = seconds between probes

    OUTPUT:
        active = list of addresses that responded
    """

    if not target_addresses:
        print("No addresses to probe.")
        return []

    print(f"\nProbing {len(target_addresses)} addresses from {mininet_host.name}")
    print("-" * 55)

    active = []
    total  = len(target_addresses)
    start_time = time.time()

    for idx, addr in enumerate(target_addresses, 1):

        print(f"[{idx:3d}/{total}] {addr} ... ", end='', flush=True)

        is_active = probe_from_host(mininet_host, addr, timeout=timeout)

        if is_active:
            active.append(addr)
            print("ACTIVE ✓")
        else:
            print("no response")

        if idx < total:
            time.sleep(rate_limit)

    # Statistics
    elapsed = time.time() - start_time
    print("-" * 55)
    print(f"Done in {elapsed:.1f}s  |  "
          f"Active: {len(active)}/{total}  |  "
          f"Hit rate: {len(active)/total*100:.1f}%")

    return active
