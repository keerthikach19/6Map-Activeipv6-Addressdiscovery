from collections import defaultdict
from ipv6_utils import get_hextets


def cluster_addresses(addresses, n_prefix=3):
    """
    Cluster IPv6 addresses by their first n_prefix hextets.

    For real-world datasets (50K), n_prefix=3 works well because
    addresses vary in hextets 0-2.

    For the Mininet dataset, addresses share hextets 0-2 ('2001','0db8','0100')
    so use n_prefix=4 to capture the group hextet as well.

    Args:
        addresses: list of IPv6 address strings
        n_prefix:  how many leading hextets to use as the cluster key (default 3)

    Returns:
        dict mapping prefix-tuple → list of addresses
    """
    clusters = defaultdict(list)

    for addr in addresses:
        hextets = get_hextets(addr)
        key = tuple(hextets[:n_prefix])
        clusters[key].append(addr)

    return clusters


def generate_patterns(clusters, n_prefix=3):
    """
    Convert cluster keys into wildcard IPv6 patterns.

    For n_prefix=3:  2001:1248:447f:*:*:*:*:*
    For n_prefix=4:  2001:0db8:0100:1000:*:*:*:*

    Args:
        clusters:  dict from cluster_addresses()
        n_prefix:  number of fixed hextets (must match what was used in clustering)

    Returns:
        list of wildcard pattern strings
    """
    patterns = []
    wildcards = ":".join(["*"] * (8 - n_prefix))

    for key in clusters:
        pattern = ":".join(key) + ":" + wildcards
        patterns.append(pattern)

    return patterns
