from ipv6_utils import get_hextets


def compute_coverage(cluster_keys, validation_addresses, n_prefix=3):
    """
    Compute what fraction of validation addresses fall into a known cluster.

    Args:
        cluster_keys:         set/dict of prefix tuples (from cluster_addresses())
        validation_addresses: list of IPv6 address strings
        n_prefix:             how many hextets to match (must match clustering depth)

    Returns:
        float in [0.0, 1.0]
    """
    if not validation_addresses:
        return 0.0

    covered = 0

    for addr in validation_addresses:
        key = tuple(get_hextets(addr)[:n_prefix])
        if key in cluster_keys:
            covered += 1

    return covered / len(validation_addresses)
