"""Physical calibration for this specific vehicle, and the pure mappings that
turn normalized commands into PWM signals.

These are measured properties of Cyber Ferret's steering linkage and ESC, not
generic constants. They live in their own hardware-free module so the mapping
can be tested without a Pi, an I2C bus, or a PCA9685 attached.
"""

from cyberferret_control import clamp


PWM_FREQUENCY_HZ = 50

STEERING_CENTER_DEG = 99.0
STEERING_LEFT_DEG = 132.0
STEERING_RIGHT_DEG = 78.0

STEERING_MIN_DEG = 78.0
STEERING_MAX_DEG = 132.0

ESC_NEUTRAL_US = 1535
ESC_FORWARD_START_US = 1631
ESC_FORWARD_MAX_US = 1665
ESC_REVERSE_START_US = 1518
ESC_REVERSE_MAX_US = 1500

# Commands smaller than this are treated as an explicit neutral rather than as
# a very small motion request the ESC would ignore anyway.
THROTTLE_DEADBAND = 0.0001

SERVO_MIN_PULSE_US = 500
SERVO_MAX_PULSE_US = 2500
SERVO_ACTUATION_RANGE_DEG = 180


def normalize_throttle(amount):
    """Clamp to [-1, 1] and collapse the deadband to an exact neutral."""

    amount = clamp(float(amount), -1.0, 1.0)

    if abs(amount) < THROTTLE_DEADBAND:
        return 0.0

    return amount


def steering_to_degrees(amount):
    """Map a steering request onto a servo angle.

    -1.0 = full physical left
     0.0 = straight
    +1.0 = full physical right
    """

    amount = clamp(float(amount), -1.0, 1.0)

    if amount < 0:
        endpoint = STEERING_LEFT_DEG
        magnitude = -amount
    else:
        endpoint = STEERING_RIGHT_DEG
        magnitude = amount

    angle = (
        STEERING_CENTER_DEG
        + (endpoint - STEERING_CENTER_DEG) * magnitude
    )

    return clamp(angle, STEERING_MIN_DEG, STEERING_MAX_DEG)


def throttle_to_pulse_us(amount):
    """Map a throttle request onto an ESC pulse width in microseconds.

    -1.0 = maximum allowed reverse
     0.0 = neutral
    +1.0 = maximum allowed forward

    The ESC has a dead zone either side of neutral, so any non-zero request
    starts at the measured break-away pulse rather than at neutral.
    """

    amount = normalize_throttle(amount)

    if amount == 0.0:
        pulse = ESC_NEUTRAL_US

    elif amount > 0:
        pulse = (
            ESC_FORWARD_START_US
            + (ESC_FORWARD_MAX_US - ESC_FORWARD_START_US) * amount
        )

    else:
        pulse = (
            ESC_REVERSE_START_US
            - (ESC_REVERSE_START_US - ESC_REVERSE_MAX_US) * -amount
        )

    return int(
        clamp(
            int(pulse),
            ESC_REVERSE_MAX_US,
            ESC_FORWARD_MAX_US,
        )
    )


def pulse_us_to_duty(pulse_us, frequency_hz=PWM_FREQUENCY_HZ):
    """Convert a pulse width into a 16-bit PCA9685 duty cycle."""

    period_us = 1_000_000 / frequency_hz
    duty = int((pulse_us / period_us) * 65535)

    return int(clamp(duty, 0, 65535))
