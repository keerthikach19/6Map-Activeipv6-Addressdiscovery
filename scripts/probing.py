# =============================================================================
# probing.py
# =============================================================================
# Sends IPv6 probe packets to target addresses and records which respond.
#
# This is the DISCOVERY component — the prober knows only the address range
# to probe, not which addresses are active. It discovers active hosts purely
# by whether an ICMPv6 Echo Reply comes back.
#
# probe_all_from_host() runs ping6 inside a Mininet host's network namespace,
# which is the correct simulation of a real prober sending ICMPv6 packets.
# =============================================================================

import time


DEFAULT_TIMEOUT = 2


def probe_from_host(mininet_host, target_address, timeout=DEFAULT_TIMEOUT):
    """
    Send a single ICMPv6 Echo Request (ping6) from inside a Mininet host.
    Returns True if the target responded, False if it timed out.

    This runs inside the host's network namespace — exactly as a real
    IPv6 scanner would send packets from its own network interface.
    """
    result = mininet_host.cmd(
        f"ping6 -c 1 -W {timeout} {target_address} 2>&1"
    )
    return "1 received" in result or "1 packets received" in result


def probe_all_from_host(mininet_host, target_addresses,
                        timeout=DEFAULT_TIMEOUT, rate_limit=0.05,
                        target_hosts=None):
    """
    Probe a list of IPv6 addresses from inside a Mininet host.

    The prober sends ICMPv6 Echo Requests to each address and records
    which ones reply. It has no prior knowledge of which are active.

    Args:
        mininet_host:     Mininet host to probe from (e.g. h1)
        target_addresses: list of IPv6 address strings to probe
        timeout:          seconds to wait per probe
        rate_limit:       seconds between probes
        target_hosts:     ignored — kept for API compatibility only

    Returns:
        list of IPv6 addresses that responded
    """

    if not target_addresses:
        print("No addresses to probe.")
        return []

    print(f"\nProbing {len(target_addresses)} addresses from {mininet_host.name}")
    print("-" * 55)

    active     = []
    total      = len(target_addresses)
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

    elapsed = time.time() - start_time
    print("-" * 55)
    print(f"Done in {elapsed:.1f}s  |  "
          f"Active: {len(active)}/{total}  |  "
          f"Hit rate: {len(active)/total*100:.1f}%")

    return active
