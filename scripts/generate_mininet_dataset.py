import random


GROUPS = [
    ("1000", "aaaa"),
    ("2000", "bbbb"),
    ("3000", "cccc"),
    ("4000", "dddd"),
    ("5000", "eeee"),
    ("6000", "ffff"),
    ("7000", "abcd"),
    ("8000", "dcba"),
]


def generate_addresses():

    addresses = []

    per_group = 13

    for h2, h3 in GROUPS:

        for _ in range(per_group):

            h4 = random.randint(1000, 9999)
            h5 = random.randint(1000, 9999)
            h6 = random.randint(1000, 9999)

            host_id = random.randint(1, 65535)

            addr = (
                f"2001:{h2}:{h3}:"
                f"{h4:x}:"
                f"{h5:x}:"
                f"{h6:x}:"
                f"0000:"
                f"{host_id:04x}"
            )

            addresses.append(addr)

    return addresses[:100]


def save_dataset(addresses):

    with open("datasets/mininet_ipv6.txt", "w") as f:

        for addr in addresses:
            f.write(addr + "\n")


if __name__ == "__main__":

    addresses = generate_addresses()

    save_dataset(addresses)

    print("Generated", len(addresses), "addresses")
