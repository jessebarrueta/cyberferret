import unittest

from cyberferret_follow import FollowController


class TestFollowController(unittest.TestCase):
    def setUp(self):
        self.follow = FollowController()

    def feed(self, x, size, frames=1):
        output = None
        for _ in range(frames):
            output = self.follow.update(True, x, size)
        return output

    def test_not_visible_proposes_nothing(self):
        output = self.follow.update(False, None, None)
        self.assertEqual(output.throttle, 0.0)
        self.assertEqual(output.steering, 0.0)
        self.assertFalse(output.acquired)

    def test_single_frame_is_not_acquired(self):
        output = self.feed(0.5, 0.05)
        self.assertFalse(output.acquired)
        self.assertEqual(output.throttle, 0.0)
        self.assertEqual(output.steering, 0.0)

    def test_acquires_after_enough_frames(self):
        output = self.feed(0.0, 0.05, frames=self.follow.acquire_frames)
        self.assertTrue(output.acquired)

    def test_loss_resets_acquisition(self):
        self.feed(0.0, 0.05, frames=5)
        self.follow.update(False, None, None)

        self.assertIsNone(self.follow.filtered_x)

        output = self.feed(0.0, 0.05)
        self.assertFalse(output.acquired)

    def test_reacquire_uses_fresh_measurement_not_stale_filter(self):
        self.feed(0.9, 0.05, frames=10)
        self.follow.update(False, None, None)

        output = self.feed(-0.9, 0.05)
        # After a loss, the filter restarts from the new measurement rather
        # than blending toward the old position.
        self.assertAlmostEqual(output.filtered_x, -0.9)

    def test_deadband_holds_steering(self):
        output = self.feed(
            self.follow.steering_deadband * 0.5,
            0.05,
            frames=10,
        )
        self.assertEqual(output.steering, 0.0)

    def test_steers_toward_target(self):
        right = self.feed(0.8, 0.05, frames=10)
        self.assertGreater(right.steering, 0.0)

        self.follow.reset()
        left = self.feed(-0.8, 0.05, frames=10)
        self.assertLess(left.steering, 0.0)

    def test_far_target_gets_max_throttle(self):
        output = self.feed(0.0, 0.05, frames=10)
        self.assertEqual(output.throttle, self.follow.max_throttle)

    def test_near_target_slows(self):
        output = self.feed(0.0, 0.20, frames=10)
        self.assertEqual(output.throttle, self.follow.slow_throttle)

    def test_reached_target_stops(self):
        output = self.feed(0.0, 0.30, frames=10)
        self.assertEqual(output.throttle, 0.0)

    def test_never_reverses(self):
        for x in (-1.0, 0.0, 1.0):
            for size in (0.01, 0.17, 0.23, 0.5):
                self.follow.reset()
                output = self.feed(x, size, frames=10)
                self.assertGreaterEqual(output.throttle, 0.0)

    def test_filtering_absorbs_a_size_spike(self):
        # One noisy giant measurement moves the filter only partway (which
        # may transiently pause throttle -- stopping is the safe direction),
        # and a couple of honest frames bring the approach back.
        self.feed(0.0, 0.05, frames=10)

        spike = self.feed(0.0, 0.9)
        self.assertLess(spike.filtered_size, 0.4)

        recovered = self.feed(0.0, 0.05, frames=3)
        self.assertLess(recovered.filtered_size, self.follow.slow_size)
        self.assertEqual(recovered.throttle, self.follow.max_throttle)


if __name__ == "__main__":
    unittest.main()
