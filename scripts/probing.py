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
#
# FIXES vs original:
#   - Default timeout raised from 2s → 4s (100-host Mininet is slower)
#   - Added pre_probe_check() to verify the prober itself is ready
#   - Progress reporting shows elapsed time and estimated remaining time
#   - rate_limit applied correctly (no sleep after final probe)
# =============================================================================

import time


DEFAULT_TIMEOUT = 4   # FIX: was 2 — too short for loaded 100-host Mininet


def pre_probe_check(mininet_host, sample_addresses, timeout=DEFAULT_TIMEOUT):
    """
    Before mass probing, verify the prober can actually reach at least one
    known-active address. If all sample pings fail, the network is not ready.

    Args:
        mininet_host:     Mininet host to probe from
        sample_addresses: small list of addresses expected to be active
        timeout:          seconds to wait per ping

    Returns:
        True if at least one address responds, False otherwise
    """
    if not sample_addresses:
        return True

    print(f"\n[Pre-probe check] Testing {len(sample_addresses)} sample address(es)...")

    for addr in sample_addresses[:3]:   # check at most 3
        result = mininet_host.cmd(f"ping6 -c 2 -W {timeout} {addr} 2>&1")
        if "1 received" in result or "2 received" in result or "1 packets received" in result:
            print(f"[Pre-probe check] ✓ {addr} responded — network is ready")
            return True

    print("[Pre-probe check] ✗ No sample addresses responded")
    return False


def probe_from_host(mininet_host, target_address, timeout=DEFAULT_TIMEOUT):
    """
    Send a single ICMPv6 Echo Request (ping6) from inside a Mininet host.
    Returns True if the target responded, False if it timed out.

    Uses -c 1 (one packet) and -W <timeout> (wait up to timeout seconds).
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
        timeout:          seconds to wait per probe (default 4)
        rate_limit:       seconds between probes (default 0.05 = 20/sec)
        target_hosts:     ignored — kept for API compatibility only

    Returns:
        list of IPv6 addresses that responded
    """

    if not target_addresses:
        print("No addresses to probe.")
        return []

    print(f"\nProbing {len(target_addresses)} addresses from {mininet_host.name}")
    print(f"  Timeout per probe : {timeout}s")
    print(f"  Rate limit        : {rate_limit}s between probes")
    estimated = len(target_addresses) * (timeout + rate_limit)
    print(f"  Estimated max time: {estimated:.0f}s  "
          f"(actual will be less — active hosts reply quickly)")
    print("-" * 60)

    active     = []
    total      = len(target_addresses)
    start_time = time.time()

    for idx, addr in enumerate(target_addresses, 1):

        # Show elapsed + simple ETA every probe
        elapsed = time.time() - start_time
        if idx > 1:
            rate    = (idx - 1) / elapsed
            eta     = (total - idx + 1) / rate if rate > 0 else 0
            eta_str = f"  ETA {eta:.0f}s"
        else:
            eta_str = ""

        print(f"[{idx:3d}/{total}] {addr} ... ", end='', flush=True)

        is_active = probe_from_host(mininet_host, addr, timeout=timeout)

        if is_active:
            active.append(addr)
            print(f"ACTIVE ✓{eta_str}")
        else:
            print(f"no response{eta_str}")

        # Rate limit — but don't sleep after the very last probe
        if idx < total:
            time.sleep(rate_limit)

    elapsed = time.time() - start_time
    print("-" * 60)
    print(f"Done in {elapsed:.1f}s  |  "
          f"Active: {len(active)}/{total}  |  "
          f"Hit rate: {len(active)/total*100:.1f}%")

    return active
