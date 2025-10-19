import subprocess
import re
import sys
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, 
    QHBoxLayout, QLabel, QSlider, QPushButton, QLineEdit, QGridLayout, QMessageBox
)
from PyQt6.QtGui import QIntValidator
from PyQt6.QtCore import Qt, QTimer, QLocale

# --- Core Kelvin to RGB Gamma Conversion Logic (Preserved from original script) ---

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
    temp_k = float(temp_k)

    # Clamp the temperature to a practical range for screen correction
    min_k = 1000.0
    max_k = 6500.0
    
    if temp_k >= max_k:
        return 1.0, 1.0, 1.0
    if temp_k <= min_k:
        temp_k = min_k # Ensure the calculation doesn't fail below min

    # --- Red Gamma Calculation (Red is clamped high for the warming effect) ---
    red = 1.0

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
    
    return red, green, blue


# --- Utility Functions for xrandr Interaction (Preserved) ---

def get_connected_displays():
    """
    Uses xrandr to find all connected display names (e.g., 'eDP-1', 'HDMI-A-1').
    """
    try:
        # Run xrandr to get display information
        result = subprocess.run(['xrandr'], capture_output=True, text=True, check=True)
        output = result.stdout
        
        # Regex to find lines with 'connected' and extract the display name
        connected_displays = re.findall(r'^(\S+)\s+connected', output, re.MULTILINE)
        
        if not connected_displays:
            return None
        return connected_displays
    
    except FileNotFoundError:
        return 'XRANDR_NOT_FOUND'
    except subprocess.CalledProcessError:
        return 'XRANDR_ERROR'
    except Exception:
        return 'UNKNOWN_ERROR'

def apply_gamma(display, r, g, b):
    """
    Applies the given R:G:B gamma values to a specific display using xrandr.
    """
    gamma_value = f"{r:.4f}:{g:.4f}:{b:.4f}"
    cmd = ['xrandr', '--output', display, '--gamma', gamma_value]
    
    try:
        # Execute the xrandr command
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Failed to set gamma for {display}. Error: {e.stderr.decode().strip()}")
        return False
    except Exception as e:
        print(f"An unexpected error occurred while setting gamma for {display}: {e}")
        return False


# --- PyQt Application Class ---

class PyFluxApp(QMainWindow):
    def __init__(self):
        super().__init__()
        
        # Check environment and display availability
        self.displays = get_connected_displays()
        
        if self.displays in ['XRANDR_NOT_FOUND', 'XRANDR_ERROR', 'UNKNOWN_ERROR']:
            self._handle_xrandr_error(self.displays)
            return

        if not self.displays:
            self._show_message_box(
                "No Displays Found", 
                "xrandr could not detect any connected displays. The application will close.", 
                QMessageBox.Icon.Critical
            )
            return

        # State Variables
        self.current_temp = 6500
        self.transition_timer = QTimer(self)
        self.transition_timer.timeout.connect(self._transition_step)
        self.start_temp = 0
        self.end_temp = 0
        self.steps = 0
        self.current_step = 0

        self.setWindowTitle("Py-Lux: Screen Color Adjuster")
        self.setMinimumWidth(400)
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint) # Nice for utilities

        self._init_ui()
        self.set_all_displays_temperature(self.current_temp) # Apply default on launch

    def _handle_xrandr_error(self, error_type):
        """Handles critical errors before UI setup."""
        if error_type == 'XRANDR_NOT_FOUND':
            msg = ("CRITICAL ERROR: 'xrandr' command is not found. "
                   "This program requires the 'xrandr' utility and an active Xorg session. "
                   "Please install it (e.g., 'sudo apt install x11-xserver-utils').")
        else:
            msg = "An error occurred while trying to run xrandr. Please check your Xorg environment."
            
        self._show_message_box("System Error", msg, QMessageBox.Icon.Critical)
        sys.exit(1) # Exit application immediately if critical error

    def _show_message_box(self, title, text, icon):
        """Helper to show a non-blocking message box."""
        msg = QMessageBox()
        msg.setIcon(icon)
        msg.setWindowTitle(title)
        msg.setText(text)
        msg.exec()

    def _init_ui(self):
        central_widget = QWidget()
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(15)

        # --- Style for Headings ---
        main_layout.addWidget(QLabel("<h1>Py-Lux Color Temperature Control</h1>"))

        # --- Display Status ---
        status_label = QLabel(f"Detected Displays: {', '.join(self.displays)}")
        status_label.setStyleSheet("font-size: 10pt; color: #555;")
        main_layout.addWidget(status_label)

        # -------------------------------------
        # SECTION 1: Fixed Temperature Control
        # -------------------------------------
        
        main_layout.addWidget(QLabel("<h2>1. Fixed Temperature (1000K - 6500K)</h2>"))

        # Temperature Display Label
        self.temp_label = QLabel(f"Current Temp: {self.current_temp}K (Gamma: 1.00:1.00:1.00)")
        self.temp_label.setStyleSheet("font-size: 14pt; font-weight: bold; padding: 5px;")
        main_layout.addWidget(self.temp_label)

        # Slider for Kelvin
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(1000, 6500)
        self.slider.setValue(self.current_temp)
        self.slider.setSingleStep(100)
        self.slider.setPageStep(500)
        self.slider.setTickPosition(QSlider.TickPosition.TicksAbove)
        self.slider.valueChanged.connect(self._slider_changed)
        main_layout.addWidget(self.slider)

        # Reset Button
        reset_button = QPushButton("Reset to Default (6500K)")
        reset_button.clicked.connect(self.reset_all_displays)
        reset_button.setStyleSheet("background-color: #f44336; color: white; padding: 10px; border-radius: 5px;")
        main_layout.addWidget(reset_button)

        # -------------------------------------
        # SECTION 2: Smooth Transition Control
        # -------------------------------------
        
        main_layout.addWidget(QLabel("<hr><h2>2. Smooth Transition (Fade)</h2>"))
        
        transition_layout = QGridLayout()

        # Inputs for Start, End, Duration
        self.start_temp_input = QLineEdit("6500")
        self.end_temp_input = QLineEdit("2700")
        self.duration_input = QLineEdit("10")
        
        # Set input validators to only allow integers
        # FIX: Replaced QLocale().createIntValidator with direct QIntValidator
        temp_validator = QIntValidator(1000, 6500, self)
        duration_validator = QIntValidator(1, 3600, self) # Duration is 1s to 3600s

        self.start_temp_input.setValidator(temp_validator)
        self.end_temp_input.setValidator(temp_validator)
        self.duration_input.setValidator(duration_validator)

        transition_layout.addWidget(QLabel("Start K:"), 0, 0)
        transition_layout.addWidget(self.start_temp_input, 0, 1)
        transition_layout.addWidget(QLabel("End K:"), 1, 0)
        transition_layout.addWidget(self.end_temp_input, 1, 1)
        transition_layout.addWidget(QLabel("Duration (s):"), 2, 0)
        transition_layout.addWidget(self.duration_input, 2, 1)
        
        main_layout.addLayout(transition_layout)

        # Transition Status Label
        self.transition_status_label = QLabel("Ready.")
        self.transition_status_label.setStyleSheet("font-style: italic; color: #333;")
        main_layout.addWidget(self.transition_status_label)
        
        # Start Transition Button
        self.fade_button = QPushButton("Start Transition")
        self.fade_button.clicked.connect(self.start_smooth_transition)
        self.fade_button.setStyleSheet("background-color: #4CAF50; color: white; padding: 10px; border-radius: 5px;")
        main_layout.addWidget(self.fade_button)

        main_layout.addStretch()
        self.setCentralWidget(central_widget)

    def _slider_changed(self, value):
        """Handles value changes from the Kelvin slider."""
        if self.transition_timer.isActive():
            return # Ignore slider input during an active transition
            
        self.current_temp = value
        self.set_all_displays_temperature(value)

    def set_all_displays_temperature(self, temp_k):
        """
        Calculates gamma for a given Kelvin temperature and applies it to all displays.
        Updates the UI label with the result.
        """
        r, g, b = kelvin_to_rgb_gamma(temp_k)
        
        for display in self.displays:
            apply_gamma(display, r, g, b)
        
        # Update the UI
        gamma_str = f"{r:.2f}:{g:.2f}:{b:.2f}"
        self.temp_label.setText(f"Current Temp: {int(temp_k)}K (Gamma: {gamma_str})")
        self.current_temp = int(temp_k)
        
        # Keep the slider in sync with the applied value
        self.slider.blockSignals(True)
        self.slider.setValue(int(temp_k))
        self.slider.blockSignals(False)
        
        return r, g, b

    def reset_all_displays(self):
        """
        Resets all connected displays to the default 1.0:1.0:1.0 gamma.
        """
        # Stop any active transition
        if self.transition_timer.isActive():
            self.transition_timer.stop()
            self.fade_button.setText("Start Transition")
            self.transition_status_label.setText("Transition interrupted and reset.")

        for display in self.displays:
            apply_gamma(display, 1.0, 1.0, 1.0)
            
        self.current_temp = 6500
        self.temp_label.setText(f"Current Temp: 6500K (Gamma: 1.00:1.00:1.00)")
        
        self.slider.blockSignals(True)
        self.slider.setValue(6500)
        self.slider.blockSignals(False)
        
        print("Color temperature reset to default (6500K / 1.0:1.0:1.0).")

    # --- Smooth Transition Logic using QTimer ---

    def start_smooth_transition(self):
        """Initializes and starts the smooth color temperature transition."""
        if self.transition_timer.isActive():
            self.transition_timer.stop()
            self.fade_button.setText("Start Transition")
            self.transition_status_label.setText("Transition cancelled.")
            return

        try:
            # Read and validate inputs
            self.start_temp = int(self.start_temp_input.text())
            self.end_temp = int(self.end_temp_input.text())
            duration_s = int(self.duration_input.text())
        except ValueError:
            self._show_message_box(
                "Input Error",
                "Please ensure Start K, End K (1000-6500), and Duration (seconds) are valid whole numbers.",
                QMessageBox.Icon.Warning
            )
            return

        if not (1000 <= self.start_temp <= 6500 and 1000 <= self.end_temp <= 6500):
            self._show_message_box(
                "Input Error",
                "Start and End temperatures must be between 1000K and 6500K.",
                QMessageBox.Icon.Warning
            )
            return

        # Setup for the timer
        self.steps = 100 # Total steps for the transition
        self.current_step = 0
        interval_ms = int((duration_s * 1000) / self.steps) # Milliseconds per step
        
        # Start the timer
        self.transition_timer.start(interval_ms)
        self.fade_button.setText("Cancel Transition")
        self.transition_status_label.setText(f"Transitioning from {self.start_temp}K to {self.end_temp}K...")

    def _transition_step(self):
        """Executed by the QTimer at each step of the transition."""
        self.current_step += 1
        
        if self.current_step > self.steps:
            # Transition complete
            self.transition_timer.stop()
            self.fade_button.setText("Start Transition")
            self.transition_status_label.setText("Transition complete.")
            return

        # Calculate interpolation ratio (0.0 to 1.0)
        ratio = self.current_step / self.steps
        
        # Calculate the current temperature using linear interpolation
        current_temp_f = self.start_temp + (self.end_temp - self.start_temp) * ratio
        current_temp = int(current_temp_f)
        
        # Apply and update UI
        r, g, b = self.set_all_displays_temperature(current_temp)

        # Update transition status label
        self.transition_status_label.setText(
            f"Step {self.current_step}/{self.steps}: {current_temp}K (Gamma: {r:.2f}:{g:.2f}:{b:.2f})"
        )


if __name__ == '__main__':
    # Critical check: Check for xrandr before starting the QApplication loop
    try:
        subprocess.run(['xrandr', '-v'], check=True, capture_output=True)
    except FileNotFoundError:
        print("CRITICAL ERROR: 'xrandr' command is not found.")
        sys.exit(1)
        
    app = QApplication(sys.argv)
    window = PyFluxApp()
    
    # Only show the window if initialization was successful (i.e., no critical errors)
    if not isinstance(window.displays, str) and window.displays is not None:
        window.show()
        sys.exit(app.exec())
