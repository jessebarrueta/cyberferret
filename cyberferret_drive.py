import threading
import time

import board
import busio
from adafruit_pca9685 import PCA9685
from adafruit_motor import servo

import cyberferret_calibration as calibration


class CyberFerretDrive:
    """The only thing in Cyber Ferret that talks to actuators.

    The signal mapping itself lives in `cyberferret_calibration`, so what
    remains here is I2C, the PCA9685, and an independent hardware watchdog.
    """

    PCA_ADDRESS = 0x40

    THROTTLE_CHANNEL = 0
    STEERING_CHANNEL = 1

    # Independent of anything in the application. If the drive layer stops
    # receiving commands at all -- because the control loop died, or the whole
    # event loop stalled -- propulsion returns to neutral without asking.
    WATCHDOG_TIMEOUT_S = 0.75
    WATCHDOG_INTERVAL_S = 0.10

    def __init__(self):
        self.i2c = busio.I2C(board.SCL, board.SDA)

        self.pca = PCA9685(
            self.i2c,
            address=self.PCA_ADDRESS,
        )
        self.pca.frequency = calibration.PWM_FREQUENCY_HZ

        self.steering_servo = servo.Servo(
            self.pca.channels[self.STEERING_CHANNEL],
            min_pulse=calibration.SERVO_MIN_PULSE_US,
            max_pulse=calibration.SERVO_MAX_PULSE_US,
            actuation_range=calibration.SERVO_ACTUATION_RANGE_DEG,
        )

        self.throttle_channel = self.pca.channels[
            self.THROTTLE_CHANNEL
        ]

        self._steering = 0.0
        self._throttle = 0.0
        self._steering_deg = calibration.STEERING_CENTER_DEG
        self._throttle_us = calibration.ESC_NEUTRAL_US

        # Written by the control thread, read by the watchdog thread.
        self._written_steering_deg = None
        self._written_throttle_us = None

        self._last_command_time = time.monotonic()
        self._shutdown = False
        self._hardware_lock = threading.Lock()

        self.stop()
        self.steer(0.0)

        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop,
            name="drive-watchdog",
            daemon=True,
        )
        self._watchdog_thread.start()

    def _set_throttle_us(self, pulse_us):
        pulse_us = int(
            max(
                calibration.ESC_REVERSE_MAX_US,
                min(calibration.ESC_FORWARD_MAX_US, int(pulse_us)),
            )
        )

        with self._hardware_lock:
            # The PCA9685 holds its own registers, so rewriting an unchanged
            # value only costs I2C time on a bus the 50 Hz loop is sharing.
            if pulse_us != self._written_throttle_us:
                self.throttle_channel.duty_cycle = (
                    calibration.pulse_us_to_duty(pulse_us)
                )
                self._written_throttle_us = pulse_us

        self._throttle_us = pulse_us

    def _touch_watchdog(self):
        self._last_command_time = time.monotonic()

    def steer(self, amount):
        """
        -1.0 = full physical left
         0.0 = straight
        +1.0 = full physical right
        """

        amount = max(-1.0, min(1.0, float(amount)))
        angle = calibration.steering_to_degrees(amount)
        rounded = round(angle, 2)

        with self._hardware_lock:
            if rounded != self._written_steering_deg:
                self.steering_servo.angle = angle
                self._written_steering_deg = rounded

        self._steering = amount
        self._steering_deg = angle
        self._touch_watchdog()

    def center(self):
        self.steer(0.0)

    def throttle(self, amount):
        """
        -1.0 = maximum allowed reverse
         0.0 = neutral
        +1.0 = maximum allowed forward
        """

        amount = calibration.normalize_throttle(amount)

        self._set_throttle_us(
            calibration.throttle_to_pulse_us(amount)
        )

        self._throttle = amount
        self._touch_watchdog()

    def forward(self, speed):
        self.throttle(abs(float(speed)))

    def reverse(self, speed):
        self.throttle(-abs(float(speed)))

    def stop(self):
        self._set_throttle_us(calibration.ESC_NEUTRAL_US)
        self._throttle = 0.0
        self._touch_watchdog()

    def adjust_throttle(self, delta):
        self.throttle(self._throttle + delta)

    def adjust_steering(self, delta):
        self.steer(self._steering + delta)

    def _watchdog_loop(self):
        while not self._shutdown:
            elapsed = (
                time.monotonic()
                - self._last_command_time
            )

            if (
                elapsed > self.WATCHDOG_TIMEOUT_S
                and self._throttle != 0.0
            ):
                print(
                    "[DRIVE] watchdog: no commands for "
                    f"{elapsed:.2f}s, forcing neutral"
                )
                self._set_throttle_us(
                    calibration.ESC_NEUTRAL_US
                )
                self._throttle = 0.0

            time.sleep(self.WATCHDOG_INTERVAL_S)

    def status(self):
        return {
            "steering": round(self._steering, 3),
            "steering_deg": round(self._steering_deg, 1),
            "throttle": round(self._throttle, 3),
            "throttle_us": self._throttle_us,
        }

    def shutdown(self):
        self._shutdown = True

        self.stop()
        self.center()

        time.sleep(0.25)

        # Join before deinit, so the watchdog cannot write to a released bus.
        self._watchdog_thread.join(
            timeout=self.WATCHDOG_INTERVAL_S * 5
        )

        with self._hardware_lock:
            self.throttle_channel.duty_cycle = 0
            self.pca.deinit()
