import ipaddress

def expand_ipv6(address):
    return ipaddress.IPv6Address(address).exploded


def get_hextets(address):
    expanded = expand_ipv6(address)
    return expanded.split(":")
