import subprocess
import argparse
import time
import re
import sys

# --- Core Kelvin to RGB Gamma Conversion Logic ---

def kelvin_to_rgb_gamma(temp_k):
    """
    Converts a color temperature in Kelvin (K) to R, G, B gamma correction values
    suitable for the 'xrandr --gamma R:G:B' command.

    This uses a simplified, practical algorithm derived from the Planckian Locus 
    to create a smooth transition from cool (daylight) to warm (night light) 
    colors, optimized for the screen's gamma ramp (0.0 to 1.0).

    Args:
        temp_k (int/float): The desired color temperature in Kelvin (e.g., 6500, 3000).

    Returns:
        tuple: (red_gamma, green_gamma, blue_gamma) as floats between 0.0 and 1.0.
    """
    temp = float(temp_k) / 100.0  # Normalized temperature value

    # Clamp the temperature to a practical range for screen correction
    # 6500K is considered the neutral (1.0:1.0:1.0) white point.
    min_k = 1000.0
    max_k = 6500.0
    
    if temp_k >= max_k:
        return 1.0, 1.0, 1.0
    if temp_k <= min_k:
        temp_k = min_k # Ensure the calculation doesn't fail below min

    # --- Red Gamma Calculation (Red should stay high) ---
    if temp <= 66.0:
        red = 1.0
    else:
        # T - 60, normalized to 100 for the range > 6600K (not used here)
        # For temperatures below 6600K (T <= 66), red is effectively 1.0 for the night effect.
        red = 1.0 # Clamping to 1.0 for the relevant range (1000K-6500K)

    # --- Green Gamma Calculation ---
    if temp_k >= 5000.0:
        # Linear fade from 1.0 at 6500K to ~0.9 at 5000K
        green = 0.8 + 0.2 * ((temp_k - 5000.0) / 1500.0)
    elif temp_k >= 2000.0:
        # Linear fade from ~0.9 at 5000K to ~0.6 at 2000K
        green = 0.6 + 0.3 * ((temp_k - 2000.0) / 3000.0)
    else:
        # Below 2000K, clamp near min
        green = 0.6 - 0.1 * ((2000.0 - temp_k) / 1000.0)
    
    green = max(0.5, min(1.0, green)) # Clamp between 0.5 and 1.0

    # --- Blue Gamma Calculation (Blue drops most significantly) ---
    if temp_k >= 6000.0:
        # Linear fade from 1.0 at 6500K to 0.9 at 6000K
        blue = 0.8 + 0.2 * ((temp_k - 6000.0) / 500.0)
    elif temp_k >= 3000.0:
        # Linear fade from ~0.8 at 6000K to ~0.3 at 3000K
        blue = 0.3 + 0.5 * ((temp_k - 3000.0) / 3000.0)
    else:
        # Below 3000K, clamp near min
        blue = 0.3 * ((temp_k - 1000.0) / 2000.0)
        
    blue = max(0.0, min(1.0, blue)) # Clamp between 0.0 and 1.0
    
    # Ensure Red is always the highest or equal to green/blue in the warm range
    red = 1.0 

    return red, green, blue


# --- Utility Functions for xrandr Interaction ---

def get_connected_displays():
    """
    Uses xrandr to find all connected display names (e.g., 'eDP-1', 'HDMI-A-1').
    """
    try:
        # Run xrandr to get display information
        result = subprocess.run(['xrandr'], capture_output=True, text=True, check=True)
        output = result.stdout
        
        # Regex to find lines with 'connected' and extract the display name
        # Example line: eDP-1 connected primary 1920x1080+0+0 (normal left inverted right x axis y axis) 345mm x 194mm
        connected_displays = re.findall(r'^(\S+)\s+connected', output, re.MULTILINE)
        
        if not connected_displays:
            print("Error: No connected displays found via xrandr.")
            sys.exit(1)
        return connected_displays
    
    except FileNotFoundError:
        print("Error: 'xrandr' command not found. This program requires an Xorg session.")
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"Error running xrandr: {e.stderr.strip()}")
        sys.exit(1)

def apply_gamma(display, r, g, b):
    """
    Applies the given R:G:B gamma values to a specific display using xrandr.
    """
    gamma_value = f"{r:.4f}:{g:.4f}:{b:.4f}"
    cmd = ['xrandr', '--output', display, '--gamma', gamma_value]
    
    # print(f"Executing: {' '.join(cmd)}") # Uncomment for debugging
    
    try:
        # We don't need to capture output, just ensure it runs
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        print(f"Failed to set gamma for display {display} with command: {' '.join(cmd)}")
        print(f"Error: {e.stderr.decode().strip()}")
    except Exception as e:
        print(f"An unexpected error occurred while setting gamma for {display}: {e}")

def set_all_displays_temperature(temp_k):
    """
    Calculates gamma for a given Kelvin temperature and applies it to all displays.
    """
    r, g, b = kelvin_to_rgb_gamma(temp_k)
    displays = get_connected_displays()
    
    for display in displays:
        apply_gamma(display, r, g, b)
    
    print(f"Color temperature set to {temp_k}K (Gamma: {r:.2f}:{g:.2f}:{b:.2f}) on {len(displays)} display(s).")
    return r, g, b

def reset_all_displays():
    """
    Resets all connected displays to the default 1.0:1.0:1.0 gamma.
    """
    displays = get_connected_displays()
    
    for display in displays:
        apply_gamma(display, 1.0, 1.0, 1.0)
        
    print(f"Color temperature reset to default (6500K / 1.0:1.0:1.0) on {len(displays)} display(s).")

# --- Transition Logic (Smooth Fading) ---

def smooth_transition(start_temp, end_temp, duration_seconds=10, steps=100):
    """
    Smoothly transitions the screen's color temperature over a duration.
    """
    print(f"Starting smooth transition from {start_temp}K to {end_temp}K over {duration_seconds} seconds...")
    
    step_duration = duration_seconds / steps
    
    for i in range(steps + 1):
        # Calculate the current temperature using linear interpolation
        current_temp = start_temp + (end_temp - start_temp) * (i / steps)
        
        # Apply the new temperature
        r, g, b = set_all_displays_temperature(current_temp)
        
        # Print update status without a newline
        sys.stdout.write(f"\rTransitioning... Current: {int(current_temp)}K (Gamma: {r:.2f}:{g:.2f}:{b:.2f})")
        sys.stdout.flush()
        
        time.sleep(step_duration)

    print("\nTransition complete.")


# --- Main CLI Execution ---

def main():
    parser = argparse.ArgumentParser(
        description="Py-Lux: A simple f.lux-like screen color temperature adjuster for Xorg/Linux.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    
    # Define a mutually exclusive group for commands
    command_group = parser.add_mutually_exclusive_group(required=True)

    command_group.add_argument(
        '-t', '--temp', 
        type=int, 
        help="Set a fixed color temperature in Kelvin (e.g., 6500 for day, 2700 for night). "
             "Range: 1000K (Warmest) to 6500K (Neutral)."
    )
    
    command_group.add_argument(
        '-r', '--reset', 
        action='store_true', 
        help="Reset the screen gamma to the default 1.0:1.0:1.0 (6500K)."
    )
    
    command_group.add_argument(
        '-f', '--fade', 
        nargs=2, 
        metavar=('START_K', 'END_K'), 
        type=int,
        help="Smoothly fade the color temperature over a period.\n"
             "Usage: -f 6500 2700 (Fades from Day to Night)."
    )

    parser.add_argument(
        '-d', '--duration', 
        type=int, 
        default=10,
        help="Duration of the fade transition in seconds (used with -f/--fade). Default is 10s."
    )

    args = parser.parse_args()

    if args.temp:
        temp = args.temp
        if temp < 1000 or temp > 6500:
            print("Warning: Temperature is outside the recommended range (1000K-6500K) for a typical night light effect.")
        set_all_displays_temperature(temp)
    
    elif args.reset:
        reset_all_displays()
        
    elif args.fade:
        start_temp = args.fade[0]
        end_temp = args.fade[1]
        smooth_transition(start_temp, end_temp, args.duration)

if __name__ == '__main__':
    # Check for xrandr dependency early
    try:
        subprocess.run(['xrandr', '-v'], check=True, capture_output=True)
    except FileNotFoundError:
        print("CRITICAL ERROR: 'xrandr' command is not found.")
        print("This program requires the 'xrandr' utility and an active Xorg session.")
        print("Please install it (e.g., 'sudo apt install x11-xserver-utils' on Debian/Pop OS).")
        sys.exit(1)
        
    main()
