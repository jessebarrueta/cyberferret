import unittest

from cyberferret_control import approach, clamp, low_pass


class TestApproach(unittest.TestCase):
    def test_moves_up_by_amount(self):
        self.assertAlmostEqual(approach(0.0, 1.0, 0.1), 0.1)

    def test_moves_down_by_amount(self):
        self.assertAlmostEqual(approach(0.5, -1.0, 0.1), 0.4)

    def test_does_not_overshoot(self):
        self.assertEqual(approach(0.95, 1.0, 0.1), 1.0)
        self.assertEqual(approach(-0.95, -1.0, 0.1), -1.0)

    def test_at_target_stays(self):
        self.assertEqual(approach(0.3, 0.3, 0.1), 0.3)


class TestLowPass(unittest.TestCase):
    def test_none_measurement_keeps_previous(self):
        self.assertEqual(low_pass(0.5, None, 0.3), 0.5)

    def test_no_history_adopts_measurement(self):
        self.assertEqual(low_pass(None, 0.7, 0.3), 0.7)

    def test_both_none(self):
        self.assertIsNone(low_pass(None, None, 0.3))

    def test_blend(self):
        self.assertAlmostEqual(low_pass(0.0, 1.0, 0.25), 0.25)

    def test_converges(self):
        value = 0.0
        for _ in range(100):
            value = low_pass(value, 1.0, 0.3)
        self.assertAlmostEqual(value, 1.0, places=5)


class TestClamp(unittest.TestCase):
    def test_inside(self):
        self.assertEqual(clamp(0.5, 0.0, 1.0), 0.5)

    def test_low(self):
        self.assertEqual(clamp(-2.0, 0.0, 1.0), 0.0)

    def test_high(self):
        self.assertEqual(clamp(2.0, 0.0, 1.0), 1.0)


if __name__ == "__main__":
    unittest.main()
