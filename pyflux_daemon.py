import subprocess
import re
import sys
import time
from datetime import datetime, timedelta
from dateutil import tz 
from astral import LocationInfo
from astral.sun import sun

# --- Configuration (User MUST edit these values) ---
# Find your latitude and longitude online (e.g., Google Maps)
LATITUDE = 37.7749  # Example: San Francisco, CA
LONGITUDE = -122.4194 # Example: San Francisco, CA
CITY_NAME = "My Location"
TIMEZONE = "America/Los_Angeles" # Use a valid timezone from the tz database (e.g., 'Europe/London')

# Color temperatures (in Kelvin)
DAY_TEMP = 5700  # Default daytime temperature (cool, white light)
NIGHT_TEMP = 3000 # Default nighttime temperature (warm, red light)

# Transition period length in minutes (e.g., 60 minutes for sunset, 60 minutes for sunrise)
TRANSITION_MINUTES = 60 

# Interval for checking and applying color changes (in seconds)
CHECK_INTERVAL_SECONDS = 60 
# ---------------------------------------------------


# --- Core Kelvin to RGB Gamma Conversion Logic (Reused) ---

def kelvin_to_rgb_gamma(temp_k):
    """
    Converts a color temperature in Kelvin (K) to R, G, B gamma correction values
    suitable for the 'xrandr --gamma R:G:B' command. (Same as original implementation)
    """
    temp_k = float(temp_k)

    min_k = 1000.0
    max_k = 6500.0
    
    if temp_k >= max_k:
        return 1.0, 1.0, 1.0
    if temp_k <= min_k:
        temp_k = min_k

    # --- Red Gamma Calculation ---
    red = 1.0

    # --- Green Gamma Calculation ---
    if temp_k >= 5000.0:
        green = 0.8 + 0.2 * ((temp_k - 5000.0) / 1500.0)
    elif temp_k >= 2000.0:
        green = 0.6 + 0.3 * ((temp_k - 2000.0) / 3000.0)
    else:
        green = 0.6 - 0.1 * ((2000.0 - temp_k) / 1000.0)
    
    green = max(0.5, min(1.0, green))

    # --- Blue Gamma Calculation ---
    if temp_k >= 6000.0:
        blue = 0.8 + 0.2 * ((temp_k - 6000.0) / 500.0)
    elif temp_k >= 3000.0:
        blue = 0.3 + 0.5 * ((temp_k - 3000.0) / 3000.0)
    else:
        blue = 0.3 * ((temp_k - 1000.0) / 2000.0)
        
    blue = max(0.0, min(1.0, blue))
    
    return red, green, blue


# --- Utility Functions for xrandr Interaction (Reused) ---

def get_connected_displays():
    """Uses xrandr to find all connected display names."""
    try:
        result = subprocess.run(['xrandr'], capture_output=True, text=True, check=True)
        output = result.stdout
        connected_displays = re.findall(r'^(\S+)\s+connected', output, re.MULTILINE)
        return connected_displays
    except Exception as e:
        print(f"Error accessing xrandr: {e}. The program cannot run without xrandr.")
        sys.exit(1)

def apply_gamma(display, r, g, b):
    """Applies the given R:G:B gamma values to a specific display using xrandr."""
    gamma_value = f"{r:.4f}:{g:.4f}:{b:.4f}"
    cmd = ['xrandr', '--output', display, '--gamma', gamma_value]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        # Suppress constant logging if xrandr fails for a non-critical reason
        # print(f"Warning: Failed to set gamma for {display}. Error: {e.stderr.decode().strip()}")
        pass
    except Exception as e:
        print(f"An unexpected error occurred while setting gamma for {display}: {e}")
        pass


# --- New Daemon Logic ---

def calculate_target_temp(location_info):
    """
    Calculates the current target Kelvin temperature based on the time of day 
    relative to sunrise and sunset.
    """
    try:
        # Get today's sun times in the specified timezone
        today_sun = sun(location_info.observer, date=datetime.now(), tzinfo=location_info.timezone)
        
        sunrise = today_sun['sunrise']
        sunset = today_sun['sunset']

    except Exception as e:
        print(f"Error calculating sun times (check TIMEZONE and coordinates): {e}")
        # Fallback to daytime temp if sun calculation fails
        return DAY_TEMP 

    # FIX: Convert the timezone string into a tzinfo object using dateutil.tz
    try:
        location_tz = tz.gettz(location_info.timezone)
        if location_tz is None:
             # If tz.gettz fails to find the timezone, use a fallback
             print(f"Warning: Timezone '{location_info.timezone}' not recognized. Using system time.")
             now = datetime.now() 
        else:
             now = datetime.now(location_tz)
    except Exception as e:
        print(f"Warning: Could not localize current time: {e}. Using system time.")
        now = datetime.now() # Fallback to naive datetime if localization fails


    # 1. NIGHT PHASE (Sunset + Transition period to Sunrise)
    # Night begins after the transition period ends
    night_start = sunset + timedelta(minutes=TRANSITION_MINUTES)
    
    # 2. MORNING TRANSITION (Sunrise - Transition period to Sunrise)
    # The smooth transition up starts TRANSITION_MINUTES before sunrise
    morning_transition_start = sunrise - timedelta(minutes=TRANSITION_MINUTES)
    
    # 3. EVENING TRANSITION (Sunset - Transition period to Sunset)
    # The smooth transition down starts TRANSITION_MINUTES before sunset
    evening_transition_start = sunset - timedelta(minutes=TRANSITION_MINUTES)

    # --- Nighttime ---
    # This handles the time from night_start (after sunset fade) until morning_transition_start (before sunrise fade)
    if now >= night_start or now < morning_transition_start:
        print(f"[{now.strftime('%H:%M:%S')}] Night: Set to {NIGHT_TEMP}K.")
        return NIGHT_TEMP

    # --- Day Time ---
    # This handles the time from sunrise until evening_transition_start
    if now >= sunrise and now < evening_transition_start:
        print(f"[{now.strftime('%H:%M:%S')}] Day: Set to {DAY_TEMP}K.")
        return DAY_TEMP
    
    # --- Evening Transition (Fading down from DAY_TEMP to NIGHT_TEMP) ---
    if now >= evening_transition_start and now < night_start:
        total_span = TRANSITION_MINUTES * 2 # Transition happens over a 2x span (before sunset to after sunset)
        elapsed_time = now - evening_transition_start
        
        # Calculate ratio (0.0 at start of transition, 1.0 at night_start)
        ratio = elapsed_time.total_seconds() / (total_span * 60)
        ratio = max(0.0, min(1.0, ratio)) # Clamp between 0 and 1

        # Interpolate: DAY_TEMP * (1-ratio) + NIGHT_TEMP * ratio
        temp = DAY_TEMP * (1 - ratio) + NIGHT_TEMP * ratio
        print(f"[{now.strftime('%H:%M:%S')}] Fading Down: {int(temp)}K (Ratio: {ratio:.2f})")
        return temp

    # --- Morning Transition (Fading up from NIGHT_TEMP to DAY_TEMP) ---
    if now >= morning_transition_start and now < sunrise:
        total_span = TRANSITION_MINUTES # Morning transition only runs until sunrise
        elapsed_time = now - morning_transition_start
        
        # Calculate ratio (0.0 at start of transition, 1.0 at sunrise)
        ratio = elapsed_time.total_seconds() / (total_span * 60)
        ratio = max(0.0, min(1.0, ratio)) # Clamp between 0 and 1
        
        # Interpolate: NIGHT_TEMP * (1-ratio) + DAY_TEMP * ratio
        temp = NIGHT_TEMP * (1 - ratio) + DAY_TEMP * ratio
        print(f"[{now.strftime('%H:%M:%S')}] Fading Up: {int(temp)}K (Ratio: {ratio:.2f})")
        return temp

    # Should not happen, but serves as a safe fallback
    return DAY_TEMP 

def main_loop():
    """
    Main loop that periodically checks the time, calculates the temperature,
    and applies the gamma correction.
    """
    # 1. Setup location
    try:
        location = LocationInfo(CITY_NAME, "State/Region", TIMEZONE, LATITUDE, LONGITUDE)
    except Exception as e:
        print(f"CRITICAL ERROR: Failed to create LocationInfo. Check your TIMEZONE and coordinates: {e}")
        sys.exit(1)
        
    # 2. Get displays once
    displays = get_connected_displays()
    if not displays:
        print("No connected displays found. Exiting.")
        sys.exit(0)

    print(f"PyFlux Daemon started.")
    print(f"Monitoring displays: {', '.join(displays)}")
    print(f"Location: {CITY_NAME} ({LATITUDE:.2f}, {LONGITUDE:.2f})")
    print("-" * 30)

    # 3. Main loop
    while True:
        try:
            target_temp = calculate_target_temp(location)
            r, g, b = kelvin_to_rgb_gamma(target_temp)
            
            for display in displays:
                apply_gamma(display, r, g, b)
            
            time.sleep(CHECK_INTERVAL_SECONDS)

        except KeyboardInterrupt:
            print("\nPyFlux Daemon stopped by user.")
            # Optional: Reset gamma to default before exiting
            # for display in displays:
            #     apply_gamma(display, 1.0, 1.0, 1.0)
            break
        except Exception as e:
            print(f"An unexpected error occurred in the main loop: {e}")
            time.sleep(CHECK_INTERVAL_SECONDS * 2) # Wait longer on error


if __name__ == '__main__':
    # Make sure 'python-dateutil' is installed
    try:
        import dateutil.tz
    except ImportError:
        print("CRITICAL ERROR: The 'python-dateutil' library is required for timezone handling.")
        print("Please install it using: pip install python-dateutil")
        sys.exit(1)

    main_loop()
