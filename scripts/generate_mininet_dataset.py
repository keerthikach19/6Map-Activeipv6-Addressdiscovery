import random

# -----------------------------------------------------------------------
# Each group has a distinct /48 prefix (first 3 hextets differ).
# This mirrors how the real 50K dataset is structured, so n_prefix=3
# clustering works for both datasets.
#
# Pattern:  2001:HHHH:GGGG:...
#   HHHH = unique per group (db80, db81, ... db87)
#   GGGG = subgroup identifier within the /48
# -----------------------------------------------------------------------
GROUPS = [
    ("db80", "aaaa"),
    ("db81", "bbbb"),
    ("db82", "cccc"),
    ("db83", "dddd"),
    ("db84", "eeee"),
    ("db85", "ffff"),
    ("db86", "abcd"),
    ("db87", "dcba"),
]


def generate_addresses(total=100):
    """
    Generate `total` synthetic IPv6 addresses spread evenly across GROUPS.

    Address format:
        2001:<group_h2>:<group_h3>:<rand_h4>:<rand_h5>:<rand_h6>:0000:<host_id>

    Each group has a unique (h2, h3) pair so the first-3-hextet cluster
    key is different per group — matching what the real dataset looks like.

    Args:
        total: total number of addresses to generate (default 100)

    Returns:
        list of IPv6 address strings
    """
    addresses = []
    per_group = total // len(GROUPS)
    remainder = total % len(GROUPS)

    for idx, (h2, h3) in enumerate(GROUPS):
        count = per_group + (1 if idx < remainder else 0)

        for _ in range(count):
            h4 = random.randint(0x1000, 0x9fff)
            h5 = random.randint(0x1000, 0x9fff)
            h6 = random.randint(0x1000, 0x9fff)
            host_id = random.randint(1, 65535)

            addr = (
                f"2001:{h2}:{h3}:"
                f"{h4:04x}:"
                f"{h5:04x}:"
                f"{h6:04x}:"
                f"0000:"
                f"{host_id:04x}"
            )
            addresses.append(addr)

    random.shuffle(addresses)
    return addresses


def save_dataset(addresses, path="datasets/mininet_ipv6.txt"):
    with open(path, "w") as f:
        for addr in addresses:
            f.write(addr + "\n")


if __name__ == "__main__":
    import sys
    total = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    addresses = generate_addresses(total)
    save_dataset(addresses)
    print(f"Generated {len(addresses)} addresses across {len(GROUPS)} groups")
    print("Sample:")
    for addr in addresses[:5]:
        print(" ", addr)
