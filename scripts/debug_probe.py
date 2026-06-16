# Quick debug script — run this on the VM to see WHY Scapy isn't getting replies
# sudo python3 scripts/debug_probe.py

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from topology import create_network
from mininet.log import setLogLevel

setLogLevel('warning')

net, hosts, active_addrs, inactive_addrs = create_network(
    num_hosts=3, active_ratio=1.0, enable_cli=False
)

try:
    h1, h2 = hosts[0], hosts[1]

    print("\n=== NETWORK STATE ===")
    print("h1 interfaces:", h1.cmd("ip -6 addr show"))
    print("h2 interfaces:", h2.cmd("ip -6 addr show"))

    print("\n=== PLAIN ping6 h1->h2 ===")
    print(h1.cmd(f"ping6 -c 2 -W 2 {h2.ipv6}"))

    print("\n=== Scapy sr1 with verbose ===")
    cmd = (
        f"python3 -c \""
        f"from scapy.all import IPv6, ICMPv6EchoRequest, sr1, conf, Ether; "
        f"conf.verb = 2; "
        f"r = sr1(IPv6(dst='{h2.ipv6}')/ICMPv6EchoRequest(), "
        f"iface='h1-eth0', timeout=3); "
        f"print('RESULT:', r.summary() if r else 'None')"
        f"\""
    )
    print(h1.cmd(cmd))

    print("\n=== Scapy with explicit src ===")
    cmd2 = (
        f"python3 -c \""
        f"from scapy.all import IPv6, ICMPv6EchoRequest, sr1, conf; "
        f"conf.verb = 2; "
        f"r = sr1(IPv6(src='{h1.ipv6}', dst='{h2.ipv6}')/ICMPv6EchoRequest(), "
        f"iface='h1-eth0', timeout=3); "
        f"print('RESULT:', r.summary() if r else 'None')"
        f"\""
    )
    print(h1.cmd(cmd2))

    print("\n=== Scapy with Ether layer (bypass NDP completely) ===")
    h2_mac = h2.cmd("cat /sys/class/net/h2-eth0/address").strip()
    print(f"h2 MAC: {h2_mac}")
    cmd3 = (
        f"python3 -c \""
        f"from scapy.all import Ether, IPv6, ICMPv6EchoRequest, srp1, conf; "
        f"conf.verb = 2; "
        f"r = srp1(Ether(dst='{h2_mac}')/IPv6(src='{h1.ipv6}', dst='{h2.ipv6}')/ICMPv6EchoRequest(), "
        f"iface='h1-eth0', timeout=3); "
        f"print('RESULT:', r.summary() if r else 'None')"
        f"\""
    )
    print(h1.cmd(cmd3))

finally:
    net.stop()
