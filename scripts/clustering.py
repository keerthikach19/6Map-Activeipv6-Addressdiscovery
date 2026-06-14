from collections import defaultdict
from ipv6_utils import get_hextets

def cluster_addresses(addresses):

    clusters = defaultdict(list)

    for addr in addresses:

        hextets = get_hextets(addr)

        key = tuple(hextets[:3])

        clusters[key].append(addr)

    return clusters


def generate_patterns(clusters):

    patterns = []

    for key in clusters:

        pattern = ":".join(key)

        pattern += ":*:*:*:*:*"

        patterns.append(pattern)

    return patterns
