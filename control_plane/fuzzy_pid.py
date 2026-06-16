import time
import math
import subprocess

# =============================================================================
# FUZZY PID CONTROLLER
# =============================================================================
# Uses fuzzy logic to dynamically tune the Proportional (Kp), Integral (Ki),
# and Derivative (Kd) gains of a PID controller.
# 
# In the 6Map context, this regulates the IPv6 probing rate to maximize
# discovery speed while avoiding network congestion (measured by RTT or drops).
# =============================================================================

class FuzzyPID:
    def __init__(self, kp_init, ki_init, kd_init):
        self.kp = kp_init
        self.ki = ki_init
        self.kd = kd_init
        
        self.prev_error = 0
        self.integral = 0
        
        # Fuzzy sets: NB (Negative Big), NM (Negative Medium), NS (Negative Small), 
        # ZO (Zero), PS (Positive Small), PM (Positive Medium), PB (Positive Big)
        self.fuzzy_sets = ['NB', 'NM', 'NS', 'ZO', 'PS', 'PM', 'PB']

        # Simplified rule base for dKp, dKi, dKd
        # Rows: Error (E), Cols: Delta Error (EC)
        self.rule_base_kp = [
            ['PB', 'PB', 'PM', 'PM', 'PS', 'ZO', 'ZO'],
            ['PB', 'PB', 'PM', 'PS', 'PS', 'ZO', 'NS'],
            ['PM', 'PM', 'PM', 'PS', 'ZO', 'NS', 'NS'],
            ['PM', 'PM', 'PS', 'ZO', 'NS', 'NM', 'NM'],
            ['PS', 'PS', 'ZO', 'NS', 'NS', 'NM', 'NM'],
            ['PS', 'ZO', 'NS', 'NM', 'NM', 'NM', 'NB'],
            ['ZO', 'ZO', 'NM', 'NM', 'NM', 'NB', 'NB']
        ]

        self.rule_base_ki = [
            ['NB', 'NB', 'NM', 'NM', 'NS', 'ZO', 'ZO'],
            ['NB', 'NB', 'NM', 'NS', 'NS', 'ZO', 'ZO'],
            ['NB', 'NM', 'NS', 'NS', 'ZO', 'PS', 'PS'],
            ['NM', 'NM', 'NS', 'ZO', 'PS', 'PM', 'PM'],
            ['NM', 'NS', 'ZO', 'PS', 'PS', 'PM', 'PB'],
            ['ZO', 'ZO', 'PS', 'PS', 'PM', 'PB', 'PB'],
            ['ZO', 'ZO', 'PS', 'PM', 'PM', 'PB', 'PB']
        ]

        self.rule_base_kd = [
            ['PS', 'NS', 'NB', 'NB', 'NB', 'NM', 'PS'],
            ['PS', 'NS', 'NB', 'NM', 'NM', 'NS', 'ZO'],
            ['ZO', 'NS', 'NM', 'NM', 'NS', 'NS', 'ZO'],
            ['ZO', 'NS', 'NS', 'NS', 'NS', 'NS', 'ZO'],
            ['ZO', 'ZO', 'ZO', 'ZO', 'ZO', 'ZO', 'ZO'],
            ['PB', 'NS', 'PS', 'PS', 'PS', 'PS', 'PB'],
            ['PB', 'PM', 'PM', 'PM', 'PS', 'PS', 'PB']
        ]

    def _membership(self, x, ranges):
        """Simple triangular membership function"""
        memberships = {}
        for i, fs in enumerate(self.fuzzy_sets):
            center = ranges[i]
            width = (ranges[-1] - ranges[0]) / 6.0  # approximate width
            
            if x <= center - width or x >= center + width:
                val = 0.0
            elif x <= center:
                val = (x - (center - width)) / width
            else:
                val = ((center + width) - x) / width
            memberships[fs] = max(0.0, min(1.0, val))
            
        return memberships

    def _defuzzify(self, e_mem, ec_mem, rule_base):
        """Center of gravity defuzzification"""
        numerator = 0.0
        denominator = 0.0
        
        # Mapping fuzzy sets to crisp output values
        val_map = {'NB': -3.0, 'NM': -2.0, 'NS': -1.0, 'ZO': 0.0, 'PS': 1.0, 'PM': 2.0, 'PB': 3.0}
        
        for i, e_key in enumerate(self.fuzzy_sets):
            for j, ec_key in enumerate(self.fuzzy_sets):
                weight = min(e_mem[e_key], ec_mem[ec_key])
                out_fs = rule_base[i][j]
                out_val = val_map[out_fs]
                
                numerator += weight * out_val
                denominator += weight
                
        if denominator == 0:
            return 0.0
        return numerator / denominator

    def compute(self, setpoint, current_value, dt):
        """Compute the next control output (e.g. rate limit in pps)"""
        error = setpoint - current_value
        delta_error = (error - self.prev_error) / dt if dt > 0 else 0
        
        # Define ranges for E and EC based on expected values (e.g. RTT in ms)
        e_ranges = [-10, -5, -2, 0, 2, 5, 10]
        ec_ranges = [-5, -2, -1, 0, 1, 2, 5]
        
        # Clip inputs to range boundaries for membership calculation to ensure gains continue tuning
        error_clipped = max(e_ranges[0], min(e_ranges[-1], error))
        delta_error_clipped = max(ec_ranges[0], min(ec_ranges[-1], delta_error))
        
        e_mem = self._membership(error_clipped, e_ranges)
        ec_mem = self._membership(delta_error_clipped, ec_ranges)
        
        # Compute delta gains
        dkp = self._defuzzify(e_mem, ec_mem, self.rule_base_kp) * 0.1
        dki = self._defuzzify(e_mem, ec_mem, self.rule_base_ki) * 0.01
        dkd = self._defuzzify(e_mem, ec_mem, self.rule_base_kd) * 0.05
        
        # Update gains
        self.kp = max(0.0, self.kp + dkp)
        self.ki = max(0.0, self.ki + dki)
        self.kd = max(0.0, self.kd + dkd)
        
        # Standard PID computation
        self.integral += error * dt
        derivative = delta_error
        
        output = (self.kp * error) + (self.ki * self.integral) + (self.kd * derivative)
        
        self.prev_error = error
        return output

# =============================================================================
# P4 SWITCH INTERFACE
# =============================================================================

def set_switch_meter_rate(rate_pps):
    """
    Update the meter rate on the BMv2 switch using simple_switch_CLI.
    The meter `probe_meter` has index 0. We set CIR and PIR to rate_pps.
    """
    # Ensure rate is positive
    rate_pps = max(1, int(rate_pps))
    
    # CIR, CBS, PIR, PBS (rate, burst)
    cmd = f"meter_set_rates probe_meter 0 {rate_pps} 10 {rate_pps} 10"
    
    try:
        subprocess.run(
            ['simple_switch_CLI', '--thrift-port', '9090'],
            input=cmd,
            text=True,
            capture_output=True,
            check=True
        )
    except subprocess.CalledProcessError as e:
        # We can silently ignore early connection errors before the switch fully boots
        if "Could not connect" not in e.stderr:
            print(f"Error setting meter: {e.stderr}")
