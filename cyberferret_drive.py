import threading
import time

import board
import busio
from adafruit_pca9685 import PCA9685
from adafruit_motor import servo


class CyberFerretDrive:
    PCA_ADDRESS = 0x40
    PWM_FREQUENCY = 50

    THROTTLE_CHANNEL = 0
    STEERING_CHANNEL = 1

    STEERING_MIN_DEG = 78
    STEERING_CENTER_DEG = 99
    STEERING_MAX_DEG = 132

    STEERING_LEFT_DEG = 132
    STEERING_RIGHT_DEG = 78

    ESC_NEUTRAL_US = 1535
    ESC_FORWARD_START_US = 1631
    ESC_FORWARD_MAX_US = 1665
    ESC_REVERSE_START_US = 1518
    ESC_REVERSE_MAX_US = 1500

    WATCHDOG_TIMEOUT_S = 0.75
    WATCHDOG_INTERVAL_S = 0.10

    def __init__(self):
        self.i2c = busio.I2C(board.SCL, board.SDA)

        self.pca = PCA9685(
            self.i2c,
            address=self.PCA_ADDRESS,
        )
        self.pca.frequency = self.PWM_FREQUENCY

        self.steering_servo = servo.Servo(
            self.pca.channels[self.STEERING_CHANNEL],
            min_pulse=500,
            max_pulse=2500,
            actuation_range=180,
        )

        self.throttle_channel = self.pca.channels[
            self.THROTTLE_CHANNEL
        ]

        self._steering = 0.0
        self._throttle = 0.0
        self._steering_deg = self.STEERING_CENTER_DEG
        self._throttle_us = self.ESC_NEUTRAL_US

        self._last_command_time = time.monotonic()
        self._shutdown = False

        self.stop()
        self.steer(0.0)

        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop,
            daemon=True,
        )
        self._watchdog_thread.start()

    def _pulse_us_to_duty(self, pulse_us):
        period_us = 1_000_000 / self.PWM_FREQUENCY
        duty = int((pulse_us / period_us) * 65535)
        return max(0, min(65535, duty))

    def _set_throttle_us(self, pulse_us):
        pulse_us = int(pulse_us)
        pulse_us = max(
            self.ESC_REVERSE_MAX_US,
            min(self.ESC_FORWARD_MAX_US, pulse_us),
        )

        self.throttle_channel.duty_cycle = (
            self._pulse_us_to_duty(pulse_us)
        )
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

        if amount < 0:
            magnitude = -amount
            angle = (
                self.STEERING_CENTER_DEG
                + (
                    self.STEERING_LEFT_DEG
                    - self.STEERING_CENTER_DEG
                )
                * magnitude
            )
        else:
            magnitude = amount
            angle = (
                self.STEERING_CENTER_DEG
                + (
                    self.STEERING_RIGHT_DEG
                    - self.STEERING_CENTER_DEG
                )
                * magnitude
            )

        angle = max(
            self.STEERING_MIN_DEG,
            min(self.STEERING_MAX_DEG, angle),
        )

        self.steering_servo.angle = angle

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

        amount = max(-1.0, min(1.0, float(amount)))

        if abs(amount) < 0.0001:
            pulse = self.ESC_NEUTRAL_US
            amount = 0.0

        elif amount > 0:
            pulse = (
                self.ESC_FORWARD_START_US
                + (
                    self.ESC_FORWARD_MAX_US
                    - self.ESC_FORWARD_START_US
                )
                * amount
            )

        else:
            magnitude = -amount
            pulse = (
                self.ESC_REVERSE_START_US
                - (
                    self.ESC_REVERSE_START_US
                    - self.ESC_REVERSE_MAX_US
                )
                * magnitude
            )

        self._set_throttle_us(pulse)
        self._throttle = amount
        self._touch_watchdog()

    def forward(self, speed):
        self.throttle(abs(float(speed)))

    def reverse(self, speed):
        self.throttle(-abs(float(speed)))

    def stop(self):
        self._set_throttle_us(self.ESC_NEUTRAL_US)
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
                self._set_throttle_us(
                    self.ESC_NEUTRAL_US
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

        self.throttle_channel.duty_cycle = 0
        self.pca.deinit()
