import unittest

import cyberferret_calibration as cal


class TestSteeringMapping(unittest.TestCase):
    def test_center(self):
        self.assertEqual(cal.steering_to_degrees(0.0), cal.STEERING_CENTER_DEG)

    def test_full_left(self):
        self.assertEqual(cal.steering_to_degrees(-1.0), cal.STEERING_LEFT_DEG)

    def test_full_right(self):
        self.assertEqual(cal.steering_to_degrees(1.0), cal.STEERING_RIGHT_DEG)

    def test_half_right_is_between_center_and_right(self):
        angle = cal.steering_to_degrees(0.5)
        self.assertLess(angle, cal.STEERING_CENTER_DEG)
        self.assertGreater(angle, cal.STEERING_RIGHT_DEG)

    def test_out_of_range_clamps(self):
        self.assertEqual(cal.steering_to_degrees(-5.0), cal.STEERING_LEFT_DEG)
        self.assertEqual(cal.steering_to_degrees(5.0), cal.STEERING_RIGHT_DEG)

    def test_never_leaves_physical_range(self):
        for i in range(-100, 101):
            angle = cal.steering_to_degrees(i / 100)
            self.assertGreaterEqual(angle, cal.STEERING_MIN_DEG)
            self.assertLessEqual(angle, cal.STEERING_MAX_DEG)

    def test_monotonic_left_to_right(self):
        # More positive command must always mean a smaller (more rightward)
        # angle on this linkage.
        previous = None
        for i in range(-100, 101):
            angle = cal.steering_to_degrees(i / 100)
            if previous is not None:
                self.assertLessEqual(angle, previous)
            previous = angle


class TestThrottleMapping(unittest.TestCase):
    def test_neutral(self):
        self.assertEqual(cal.throttle_to_pulse_us(0.0), cal.ESC_NEUTRAL_US)

    def test_deadband_is_neutral(self):
        self.assertEqual(cal.throttle_to_pulse_us(0.00005), cal.ESC_NEUTRAL_US)
        self.assertEqual(cal.throttle_to_pulse_us(-0.00005), cal.ESC_NEUTRAL_US)

    def test_minimum_forward_starts_at_breakaway(self):
        pulse = cal.throttle_to_pulse_us(0.001)
        self.assertGreaterEqual(pulse, cal.ESC_FORWARD_START_US)

    def test_full_forward(self):
        self.assertEqual(cal.throttle_to_pulse_us(1.0), cal.ESC_FORWARD_MAX_US)

    def test_minimum_reverse_starts_at_breakaway(self):
        pulse = cal.throttle_to_pulse_us(-0.001)
        self.assertLessEqual(pulse, cal.ESC_REVERSE_START_US)

    def test_full_reverse(self):
        self.assertEqual(cal.throttle_to_pulse_us(-1.0), cal.ESC_REVERSE_MAX_US)

    def test_out_of_range_clamps(self):
        self.assertEqual(cal.throttle_to_pulse_us(10.0), cal.ESC_FORWARD_MAX_US)
        self.assertEqual(cal.throttle_to_pulse_us(-10.0), cal.ESC_REVERSE_MAX_US)

    def test_never_leaves_calibrated_range(self):
        for i in range(-100, 101):
            pulse = cal.throttle_to_pulse_us(i / 100)
            self.assertGreaterEqual(pulse, cal.ESC_REVERSE_MAX_US)
            self.assertLessEqual(pulse, cal.ESC_FORWARD_MAX_US)

    def test_forward_monotonic(self):
        previous = None
        for i in range(1, 101):
            pulse = cal.throttle_to_pulse_us(i / 100)
            if previous is not None:
                self.assertGreaterEqual(pulse, previous)
            previous = pulse


class TestDutyConversion(unittest.TestCase):
    def test_neutral_pulse(self):
        # 1535us of a 20000us period, in 16-bit duty units.
        expected = int((1535 / 20000) * 65535)
        self.assertEqual(cal.pulse_us_to_duty(1535), expected)

    def test_zero(self):
        self.assertEqual(cal.pulse_us_to_duty(0), 0)

    def test_clamps_to_16_bits(self):
        self.assertEqual(cal.pulse_us_to_duty(50_000), 65535)


if __name__ == "__main__":
    unittest.main()
