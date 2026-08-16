import board
import busio
from adafruit_pca9685 import PCA9685


class CyberFerretDrive:
    # Empirically calibrated on Cyber Ferret.
    STEERING_CENTER_DEG = 99.0
    STEERING_RANGE_DEG = 25.0

    ESC_NEUTRAL_US = 1535
    ESC_FORWARD_START_US = 1631
    ESC_FORWARD_MAX_US = 1665
    ESC_REVERSE_START_US = 1518
    ESC_REVERSE_MAX_US = 1500

    STEERING_CHANNEL = 0
    THROTTLE_CHANNEL = 1

    def __init__(self):
        i2c = busio.I2C(board.SCL, board.SDA)
        self.pca = PCA9685(i2c)
        self.pca.frequency = 50

        self._steering_deg = self.STEERING_CENTER_DEG
        self._throttle_us = self.ESC_NEUTRAL_US

        self.center()
        self.stop()

    @staticmethod
    def _pulse_us_to_duty_cycle(pulse_us, frequency_hz=50):
        period_us = 1_000_000.0 / frequency_hz
        return int((pulse_us / period_us) * 0xFFFF)

    @staticmethod
    def _servo_deg_to_pulse_us(degrees):
        # Conventional 0–180° servo mapping.
        degrees = max(0.0, min(180.0, float(degrees)))
        return 500.0 + (degrees / 180.0) * 2000.0

    def _write_pulse(self, channel, pulse_us):
        self.pca.channels[channel].duty_cycle = self._pulse_us_to_duty_cycle(
            pulse_us,
            self.pca.frequency,
        )

    def steer(self, value):
        value = max(-1.0, min(1.0, float(value)))
        degrees = self.STEERING_CENTER_DEG + value * self.STEERING_RANGE_DEG
        self._steering_deg = degrees
        self._write_pulse(
            self.STEERING_CHANNEL,
            self._servo_deg_to_pulse_us(degrees),
        )

    def center(self):
        self.steer(0.0)

    def throttle(self, value):
        value = max(-1.0, min(1.0, float(value)))

        if abs(value) < 0.001:
            pulse = self.ESC_NEUTRAL_US
        elif value > 0:
            pulse = self.ESC_FORWARD_START_US + value * (
                self.ESC_FORWARD_MAX_US - self.ESC_FORWARD_START_US
            )
        else:
            magnitude = abs(value)
            pulse = self.ESC_REVERSE_START_US + magnitude * (
                self.ESC_REVERSE_MAX_US - self.ESC_REVERSE_START_US
            )

        self._throttle_us = int(round(pulse))
        self._write_pulse(self.THROTTLE_CHANNEL, self._throttle_us)

    def stop(self):
        self._throttle_us = self.ESC_NEUTRAL_US
        self._write_pulse(self.THROTTLE_CHANNEL, self._throttle_us)

    def status(self):
        return {
            "throttle_us": self._throttle_us,
            "steering_deg": self._steering_deg,
        }

    def shutdown(self):
        try:
            self.stop()
            self.center()
        finally:
            self.pca.deinit()
