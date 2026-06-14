import random


def generate_candidates(patterns, per_pattern=5):
    """
    Convert wildcard patterns into candidate IPv6 addresses.

    Example:

    Pattern:
    2001:db8:1:*:*:*:*:*

    Might generate:
    2001:db8:1:1234:5678:abcd:1111:2222
    """

    candidates = []

    for pattern in patterns:

        parts = pattern.split(":")

        for _ in range(per_pattern):

            addr_parts = []

            for part in parts:

                if part == "*":
                    addr_parts.append(
                        f"{random.randint(0,65535):x}"
                    )
                else:
                    addr_parts.append(part)

            candidates.append(":".join(addr_parts))

    return candidates
