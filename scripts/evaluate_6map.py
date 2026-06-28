import sys
import os
import time
import threading
import re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "control_plane"))

from mininet_bmv2 import create_p4_network
from fuzzy_pid import FuzzyPID, set_switch_meter_rate

def get_ping_rtt(node, target_ip):
    """
    Execute ping6 on a mininet node and parse the output.
    Returns (rtt_ms, success).
    If success is False, rtt_ms is None (indicates packet loss/timeout).
    """
    output = node.cmd(f"ping6 -c 1 -W 1 {target_ip}")
    # Regex to find time=XX.XX ms
    match = re.search(r"time=([\d\.]+)\s*ms", output)
    if match:
        try:
            return float(match.group(1)), True
        except ValueError:
            pass
    return None, False

# =============================================================================
# BACKGROUND FUZZY PID DAEMON
# =============================================================================
class FuzzyPIDDaemon(threading.Thread):
    def __init__(self, target_rtt_ms=5.0):
        super().__init__()
        self.daemon = True
        self.running = True
        self.current_rate = 100.0  # start at 100 pps
        
        # Initialize FuzzyPID with base gains
        self.controller = FuzzyPID(kp_init=1.0, ki_init=0.1, kd_init=0.05)
        
        # Thread safety lock
        self.lock = threading.Lock()
        # List to store tuples of (rtt_ms, success) from monitor
        self.rtt_samples = []
        
        # Dynamic RTT & Congestion variables
        self.rtt_history = []               # sliding window of successful RTTs
        self.rtt_min = None                 # baseline propagation delay
        self.queue_delay_budget = 2.0       # dynamic queue delay budget in ms
        self.min_budget = 0.5               # minimum allowed budget
        self.max_budget = 20.0              # maximum allowed budget
        self.target_rtt = target_rtt_ms     # current setpoint, starts with default
        self.measured_rtt = 0.0             # current smoothed RTT
        self.loss_rate = 0.0
        self.jitter = 0.0

    def run(self):
        last_time = time.time()
        while self.running:
            time.sleep(0.5)  # control loop interval
            
            now = time.time()
            dt = now - last_time
            last_time = now
            
            # 1. Thread-safely extract and clear accumulated samples
            with self.lock:
                samples = list(self.rtt_samples)
                self.rtt_samples.clear()
                
            if samples:
                # Filter successful ping RTTs and failures
                successful_rtts = [r for r, success in samples if success]
                num_failures = sum(1 for r, success in samples if not success)
                total_samples = len(samples)
                
                # Compute loss rate
                self.loss_rate = num_failures / total_samples
                
                # Update history with successful measurements
                if successful_rtts:
                    self.rtt_history.extend(successful_rtts)
                    self.rtt_history = self.rtt_history[-30:] # keep last 30 samples
                    self.rtt_min = min(self.rtt_history)
                    
                    # Compute smoothed measured RTT (exponential moving average or simple average of current step)
                    step_avg_rtt = sum(successful_rtts) / len(successful_rtts)
                    if self.measured_rtt == 0.0:
                        self.measured_rtt = step_avg_rtt
                    else:
                        # EMA with alpha = 0.3 to reduce measurement noise
                        self.measured_rtt = 0.3 * step_avg_rtt + 0.7 * self.measured_rtt
                        
                    # Compute jitter (mean absolute difference between consecutive samples in history)
                    if len(self.rtt_history) > 1:
                        self.jitter = sum(abs(self.rtt_history[i] - self.rtt_history[i-1]) for i in range(1, len(self.rtt_history))) / (len(self.rtt_history) - 1)
                    else:
                        self.jitter = 0.0
                
                # If there are no successful RTTs (all pings failed), we treat it as 100% loss
                # and assign a penalty measured RTT to force rate reduction
                if not successful_rtts:
                    self.measured_rtt = self.target_rtt + 15.0 # penalty
                    self.jitter = 5.0
            else:
                # No samples collected in this period, keep previous states but don't do penalty
                pass

            # 2. Dynamic budget and setpoint adjustment
            if self.rtt_min is not None:
                # Determine congestion based on:
                # - loss_rate > 0 (direct drop)
                # - jitter > 0.5 * queue_delay_budget (unstable queue)
                # - queuing delay (measured_rtt - rtt_min) exceeds budget
                current_queue_delay = max(0.0, self.measured_rtt - self.rtt_min)
                
                is_congested = (self.loss_rate > 0.0 or 
                                self.jitter > (0.5 * self.queue_delay_budget) or 
                                current_queue_delay > self.queue_delay_budget)
                
                if is_congested:
                    # Multiplicative decrease of budget
                    backoff_factor = 0.5 if self.loss_rate > 0.3 else 0.8
                    self.queue_delay_budget = max(self.min_budget, self.queue_delay_budget * backoff_factor)
                else:
                    # Additive increase of budget when healthy
                    self.queue_delay_budget = min(self.max_budget, self.queue_delay_budget + 0.2)
                
                self.target_rtt = self.rtt_min + self.queue_delay_budget
            else:
                # Fallback if no minimum RTT is recorded yet
                pass

            # 3. Fuzzy controller calculates the needed adjustment 
            adjustment = self.controller.compute(self.target_rtt, self.measured_rtt, dt)
            
            self.current_rate = max(10.0, min(1000.0, self.current_rate + adjustment))
            
            # Print status to stdout for real-time visibility
            print(f"[PID Daemon] Rate: {self.current_rate:6.1f} pps | "
                  f"RTT Min: {f'{self.rtt_min:.2f}' if self.rtt_min is not None else 'N/A'} ms | "
                  f"Budget: {self.queue_delay_budget:.2f} ms | "
                  f"Target RTT: {self.target_rtt:.2f} ms | "
                  f"Meas RTT: {self.measured_rtt:.2f} ms | "
                  f"Loss: {self.loss_rate * 100:5.1f}% | "
                  f"Jitter: {self.jitter:.2f} ms | "
                  f"Adjust: {adjustment:+.2f}")
            
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
            rtt, success = get_ping_rtt(h2, "2001:db8:1::1")
            with fuzzy_daemon.lock:
                fuzzy_daemon.rtt_samples.append((rtt, success))
            time.sleep(0.15)

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
    parser.add_argument("--target-rtt", type=float, default=10.0, help="Initial reference/backup target RTT (ms) before dynamic scaling adapts it")
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
        # Save results to file
        os.makedirs("outputs", exist_ok=True)
        with open("outputs/discovery_results.txt", "a") as f:
            f.write(f"{'Hosts':>8}  {'Active':>6}  {'Found':>6}  {'Hit%':>7}  {'Prec%':>7}  {'FP%':>5}  {'Time(s)':>8}\n")
            prec = len(true_positives) / len(discovered) * 100 if discovered else 0
            fp_pct = len(false_positives) / len(discovered) * 100 if discovered else 0
            f.write(
                f"{args.hosts:>8}  "
                f"{len(ground_truth):>6}  "
                f"{len(true_positives):>6}  "
                f"{hit_rate:>6.1f}%  "
                f"{prec:>6.1f}%  "
                f"{fp_pct:>4.1f}%  "
                f"{float(elapsed):>8.1f}\n"
            )
        print(f"\nResults saved to outputs/discovery_results.txt")
        
    finally:
        if fuzzy_daemon:
            fuzzy_daemon.stop()
        if 'net' in locals():
            print("\n*** Stopping network...")
            net.stop()
