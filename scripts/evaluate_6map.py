import sys
import os
import time
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "control_plane"))

from mininet_bmv2 import create_p4_network
from fuzzy_pid import FuzzyPID, set_switch_meter_rate

# =============================================================================
# BACKGROUND FUZZY PID DAEMON
# =============================================================================
class FuzzyPIDDaemon(threading.Thread):
    def __init__(self, target_rtt_ms=5.0):
        super().__init__()
        self.daemon = True
        self.target_rtt = target_rtt_ms
        self.running = True
        self.current_rate = 100.0  # start at 100 pps
        
        # Initialize FuzzyPID with base gains
        self.controller = FuzzyPID(kp_init=1.0, ki_init=0.1, kd_init=0.05)
        
        # Shared state that the prober updates
        self.measured_rtt = 0.0

    def run(self):
        last_time = time.time()
        while self.running:
            time.sleep(0.5)  # control loop interval
            
            now = time.time()
            dt = now - last_time
            last_time = now
            
            # The fuzzy controller calculates the needed adjustment 
            # to the scanning rate based on how far we are from the target RTT
            # If measured RTT > target RTT, output is negative (slow down)
            # If measured RTT < target RTT, output is positive (speed up)
            adjustment = self.controller.compute(self.target_rtt, self.measured_rtt, dt)
            
            self.current_rate = max(10.0, min(1000.0, self.current_rate + adjustment))
            
            # Update the P4 switch meter
            set_switch_meter_rate(self.current_rate)

    def stop(self):
        self.running = False


# =============================================================================
# FAST PROBER (Uses parallel shell pings)
# =============================================================================
def run_prober(h1, h2, target_addrs, fuzzy_daemon):
    """
    Runs parallel pings from h1.
    While running, periodically updates fuzzy_daemon.measured_rtt based on 
    a sample ping, so the control plane can adjust the P4 switch rate.
    """
    total = len(target_addrs)
    batch_size = 20
    timeout = 3
    
    print(f"\n--- Starting 6Map Prober ---")
    print(f"Target count : {total}")
    print(f"Batch size   : {batch_size}")
    print(f"Max Timeout  : {timeout}s")
    
    # 1. Write targets to file
    targets_file = f"/tmp/6map_targets_{h1.name}.txt"
    results_file = f"/tmp/6map_results_{h1.name}.txt"
    script_file  = f"/tmp/6map_probe_{h1.name}.sh"

    with open(targets_file, 'w') as f:
        for addr in target_addrs:
            f.write(addr + "\n")

    # 2. Bash script that launches pings in parallel
    script_content = f"""#!/bin/bash
> "{results_file}"
count=0
while IFS= read -r addr; do
    ( ping6 -c 1 -W {timeout} "$addr" > /dev/null 2>&1 && echo "$addr" >> "{results_file}" ) &
    count=$((count + 1))
    if [ $((count % {batch_size})) -eq 0 ]; then
        wait
    fi
done < "{targets_file}"
wait
"""
    with open(script_file, 'w') as f:
        f.write(script_content)
    os.chmod(script_file, 0o755)

    # 3. Background thread to monitor RTT and feed Fuzzy PID
    monitor_running = True
    def rtt_monitor():
        # Use h2 to monitor RTT to h1, since h1 is busy running the probe script.
        # Mininet node.cmd() is not thread-safe for the same node.
        while monitor_running:
            t0 = time.time()
            # h2 pings h1. They have static neighbor entries for each other.
            h2.cmd(f"ping6 -c 1 -W 1 2001:db8:1::1")
            rtt_ms = (time.time() - t0) * 1000.0
            fuzzy_daemon.measured_rtt = rtt_ms
            time.sleep(0.5)

    monitor_thread = threading.Thread(target=rtt_monitor)
    monitor_thread.daemon = True
    monitor_thread.start()

    # 4. Run the probing script
    start_time = time.time()
    h1.cmd(f"bash {script_file}")
    elapsed = time.time() - start_time
    
    # 5. Stop monitor
    monitor_running = False
    monitor_thread.join()

    # 6. Collect results
    active = set()
    if os.path.exists(results_file):
        with open(results_file) as f:
            active = set(line.strip() for line in f if line.strip())

    return active, elapsed


# =============================================================================
# MAIN EVALUATION
# =============================================================================
if __name__ == "__main__":
    import argparse
    from mininet.log import setLogLevel
    setLogLevel('warning')

    parser = argparse.ArgumentParser(description="6Map Phase B Evaluation")
    parser.add_argument("--hosts", type=int, default=100, help="Total number of hosts to simulate")
    parser.add_argument("--active-ratio", type=float, default=0.7, help="Ratio of active hosts (0.0 to 1.0)")
    parser.add_argument("--target-rtt", type=float, default=10.0, help="Target RTT for Fuzzy PID in milliseconds")
    args = parser.parse_args()

    if args.hosts < 2:
        print("Error: Number of hosts must be at least 2.")
        sys.exit(1)

    fuzzy_daemon = None
    try:
        # Create the network
        print("*** Initializing Mininet Network (this may take a few seconds)...")
        net, hosts, active_addrs = create_p4_network(num_hosts=args.hosts, active_ratio=args.active_ratio)
        h1 = hosts[0]
        h2 = hosts[1]
        
        # Start the Fuzzy PID Control Plane ONLY AFTER network is ready
        fuzzy_daemon = FuzzyPIDDaemon(target_rtt_ms=args.target_rtt)
        fuzzy_daemon.start()

        # We probe everyone except ourselves
        target_addrs = [f"2001:db8:1::{i}" for i in range(2, args.hosts + 1)]
        ground_truth = set(active_addrs) - {h1.ipv6}
        
        # Run prober
        discovered, elapsed = run_prober(h1, h2, target_addrs, fuzzy_daemon)
        
        # Calculate Metrics
        true_positives = discovered.intersection(ground_truth)
        false_positives = discovered - ground_truth
        false_negatives = ground_truth - discovered
        
        hit_rate = len(true_positives) / len(ground_truth) * 100 if ground_truth else 0
        
        print("\n--- Target Discovery Status ---")
        for addr in target_addrs:
            is_active = addr in discovered
            status_symbol = "✓" if is_active else "✗"
            status_text = "Active" if is_active else "Inactive / Not Found"
            print(f"  {addr:<16} : [ {status_symbol} {status_text} ]")

        print("\n" + "=" * 60)
        print("6MAP PHASE B: P4 BMv2 + FUZZY PID EVALUATION RESULTS")
        print("=" * 60)
        print(f"Total hosts simulated: {args.hosts}")
        print(f"Active ratio         : {args.active_ratio}")
        print(f"Total targets probed : {len(target_addrs)}")
        print(f"Total active targets : {len(ground_truth)}")
        print(f"Discovered active    : {len(discovered)}")
        print(f"Hit Rate (Recall)    : {hit_rate:.1f}%")
        print(f"False Positives      : {len(false_positives)}")
        print(f"Time Elapsed         : {elapsed:.2f} s")
        print(f"Average Probing Rate : {len(target_addrs)/elapsed:.1f} pps")
        print("=" * 60)
        
    finally:
        if fuzzy_daemon:
            fuzzy_daemon.stop()
        if 'net' in locals():
            print("\n*** Stopping network...")
            net.stop()
