import os
import time
import subprocess
from mininet.net import Mininet
from mininet.node import Switch, Host
from mininet.log import setLogLevel, info
from mininet.link import TCLink

# =============================================================================
# BMv2 CUSTOM SWITCH CLASS
# =============================================================================
class P4Switch(Switch):
    """Custom Switch for Mininet using BMv2 simple_switch"""
    def __init__(self, name, json_path, thrift_port=9090, **kwargs):
        Switch.__init__(self, name, **kwargs)
        self.json_path = json_path
        self.thrift_port = thrift_port
        self.sw_path = "simple_switch"
        self.log_path = f"/tmp/p4s.{name}.log"

    def start(self, controllers):
        info(f"Starting P4 switch {self.name}...\n")
        
        # Clean up stale IPC sockets from previous crashes
        os.system(f"rm -f /tmp/bmv2-*")

        args = [
            self.sw_path,
            "--log-file", self.log_path,
            "--thrift-port", str(self.thrift_port),
            self.json_path
        ]
        
        # Add port mappings
        for intf in self.intfList():
            if not intf.IP():
                # Extract port number assuming interface names like s1-eth1
                try:
                    port_num = int(intf.name.split('-eth')[1])
                    args.extend(["-i", f"{port_num}@{intf.name}"])
                except Exception:
                    pass

        # Run switch in background using a shell script to avoid PTY command line length limits
        cmd_str = " ".join(args) + f" > {self.log_path}.out 2>&1 &"
        script_path = f"/tmp/start_{self.name}.sh"
        with open(script_path, "w") as f:
            f.write("#!/bin/bash\n")
            f.write(cmd_str + "\n")
        os.chmod(script_path, 0o755)
        self.cmd(f"bash {script_path}")

    def stop(self):
        info(f"Stopping P4 switch {self.name}...\n")
        self.cmd("kill %" + self.sw_path)
        Switch.stop(self)

# =============================================================================
# MININET TOPOLOGY SETUP
# =============================================================================
def create_p4_network(num_hosts=100, active_ratio=1.0):
    """
    Sets up a Mininet topology using the BMv2 switch running 6map_switch.p4.
    Applies the robust static IP configuration to avoid multicast storms.
    """
    
    # 1. Compile P4 code first
    p4_file = "p4src/6map_switch.p4"
    out_dir = "p4src/out"
    json_file = f"{out_dir}/6map_switch.json"
    
    info("*** Compiling P4 program...\n")
    os.makedirs(out_dir, exist_ok=True)
    subprocess.run(["p4c", "-b", "bmv2", "-o", out_dir, p4_file], check=True)
    
    # 2. Setup Mininet
    net = Mininet(controller=None, link=TCLink, autoSetMacs=True)
    
    info("*** Creating P4 switch\n")
    s1 = net.addSwitch('s1', cls=P4Switch, json_path=json_file, thrift_port=9090)
    
    hosts = []
    for i in range(1, num_hosts + 1):
        host = net.addHost(f'h{i}', ip=None)
        # s1-eth1 corresponds to h1, s1-eth2 to h2, etc.
        net.addLink(host, s1, port1=0, port2=i)
        hosts.append(host)
        
    info("*** Starting network\n")
    net.start()
    
    time.sleep(2) # Give simple_switch time to boot
    
    # 3. Configure Hosts (Storm-Proof IPv6 setup)
    info("*** Configuring host interfaces\n")
    
    import random
    IPV6_PREFIX = "2001:db8:1"
    num_active = int(num_hosts * active_ratio)
    
    # h1 (index 1) must always be active to run the prober.
    # Randomly select other active host indices.
    active_indices = {1}
    if num_hosts > 1:
        other_indices = list(range(2, num_hosts + 1))
        num_others_needed = min(num_active - 1, len(other_indices))
        if num_others_needed > 0:
            active_indices.update(random.sample(other_indices, num_others_needed))
            
    active_hosts = [hosts[i-1] for i in sorted(active_indices)]
    inactive_hosts = [hosts[i-1] for i in range(1, num_hosts + 1) if i not in active_indices]
    
    active_addrs = []
    
    for host in active_hosts:
        i = int(host.name[1:])
        ipv6_addr = f"{IPV6_PREFIX}::{i}"
        ipv6_cidr = f"{ipv6_addr}/64"
        iface = f"{host.name}-eth0"
        
        # Configure active host (disable DAD/RS before bringing up)
        cmd = (
            f"sysctl -qw net.ipv6.conf.{iface}.dad_transmits=0; "
            f"sysctl -qw net.ipv6.conf.{iface}.accept_dad=0; "
            f"sysctl -qw net.ipv6.conf.{iface}.router_solicitations=0; "
            f"ip link set {iface} up; "
            f"ip -6 addr add {ipv6_cidr} dev {iface} 2>/dev/null; "
            f"ip -6 route replace {IPV6_PREFIX}::/64 dev {iface} metric 1 2>/dev/null; "
            f"sysctl -qw net.ipv6.conf.all.forwarding=1"
        )
        host.cmd(f"bash -c '{cmd}'")
        host.ipv6 = ipv6_addr
        host.mac = host.cmd(f"cat /sys/class/net/{iface}/address").strip()
        active_addrs.append(ipv6_addr)
        
    for host in inactive_hosts:
        i = int(host.name[1:])
        iface = f"{host.name}-eth0"
        # Disable IPv6 completely on inactive hosts
        host.cmd(
            f"sysctl -qw net.ipv6.conf.{iface}.disable_ipv6=1; "
            f"ip link set {iface} up"
        )
        host.ipv6 = f"{IPV6_PREFIX}::{i}"
        
    # 3.5 Populate Static Neighbor Entries to bypass NDP (P4 switch drops multicast)
    info("*** Populating static neighbor entries\n")
    h1 = active_hosts[0]
    h1_iface = f"{h1.name}-eth0"
    
    # h1 needs to know everyone's MAC
    neigh_commands = []
    for host in active_hosts:
        if host == h1:
            continue
        neigh_commands.append(f"ip -6 neigh replace {host.ipv6} lladdr {host.mac} dev {h1_iface} nud permanent 2>/dev/null")
        # Everyone else needs to know h1's MAC to reply
        other_iface = f"{host.name}-eth0"
        host.cmd(f"ip -6 neigh replace {h1.ipv6} lladdr {h1.mac} dev {other_iface} nud permanent 2>/dev/null")

    # Write h1's entries to a file to avoid PTY overflow
    neigh_script = f"/tmp/6map_neigh_{h1.name}.sh"
    with open(neigh_script, 'w') as f:
        f.write("#!/bin/bash\n" + "\n".join(neigh_commands) + "\n")
    h1.cmd(f"bash {neigh_script}")

        
    # 4. Wait for simple_switch Thrift server to be ready
    info("*** Waiting for BMv2 Thrift server on port 9090...\n")
    max_retries = 10
    ready = False
    for r in range(max_retries):
        res = subprocess.run(['simple_switch_CLI', '--thrift-port', '9090'], 
                             input="echo", text=True, capture_output=True)
        if "Could not connect" not in res.stdout and "Could not connect" not in res.stderr:
            ready = True
            break
        time.sleep(1)
        
    if not ready:
        info("*** ERROR: BMv2 Thrift server failed to start. Check logs.\n")
    
    # 5. Populate Switch Forwarding Table via simple_switch_CLI
    info("*** Populating P4 switch forwarding table\n")
    commands = []
    for host in active_hosts:
        i = int(host.name[1:])
        iface = f"{host.name}-eth0"
        mac = host.cmd(f"cat /sys/class/net/{iface}/address").strip()
        # The P4 table is mac_forward, action is forward
        commands.append(f"table_add mac_forward forward {mac} => {i}")
        
    cli_input = "\n".join(commands) + "\n"
    subprocess.run(['simple_switch_CLI', '--thrift-port', '9090'], input=cli_input, text=True, capture_output=True)
    
    # Set initial meter rate (e.g. 50 pps)
    subprocess.run(['simple_switch_CLI', '--thrift-port', '9090'], input="meter_set_rates probe_meter 0 50 10 50 10\n", text=True, capture_output=True)

    info("*** Network setup complete\n")
    return net, hosts, active_addrs
