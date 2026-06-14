from ipv6_utils import get_hextets

def compute_coverage(cluster_keys, validation_addresses):

    covered = 0

    for addr in validation_addresses:

        key = tuple(get_hextets(addr)[:3])

        if key in cluster_keys:
            covered += 1

    if len(validation_addresses) == 0:
        return 0   

    return covered / len(validation_addresses)
