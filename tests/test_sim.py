import math
import unittest

try:
    import cv2  # noqa: F401
    import numpy  # noqa: F401
    HAS_CV = True
except ImportError:
    HAS_CV = False

if HAS_CV:
    from cyberferret_follow import FollowController
    from cyberferret_sim import FerretSimulation
    from cyberferret_vision import ArucoVision


@unittest.skipUnless(HAS_CV, "opencv/numpy not installed")
class TestSimulationRendering(unittest.TestCase):
    def test_real_detector_sees_simulated_marker(self):
        simulation = FerretSimulation(marker_xy=(1.0, 0.0))
        vision = ArucoVision(target_id=7)

        result = vision.detect_jpeg(simulation.render_jpeg())

        self.assertTrue(result["visible"])
        self.assertEqual(result["id"], 7)
        # Dead ahead: near the image center.
        self.assertLess(abs(result["x"]), 0.1)

    def test_marker_to_the_left_appears_left(self):
        simulation = FerretSimulation(marker_xy=(1.5, 0.5))
        vision = ArucoVision(target_id=7)

        result = vision.detect_jpeg(simulation.render_jpeg())

        self.assertTrue(result["visible"])
        self.assertLess(result["x"], -0.1)

    def test_marker_behind_is_not_rendered(self):
        simulation = FerretSimulation(marker_xy=(-1.0, 0.0))
        vision = ArucoVision(target_id=7)

        result = vision.detect_jpeg(simulation.render_jpeg())

        self.assertFalse(result["visible"])

    def test_closer_marker_is_bigger(self):
        far = FerretSimulation(marker_xy=(2.0, 0.0))
        near = FerretSimulation(marker_xy=(0.8, 0.0))
        vision = ArucoVision(target_id=7)

        far_size = vision.detect_jpeg(far.render_jpeg())["size"]
        near_size = vision.detect_jpeg(near.render_jpeg())["size"]

        self.assertGreater(near_size, far_size)


@unittest.skipUnless(HAS_CV, "opencv/numpy not installed")
class TestClosedLoopFollow(unittest.TestCase):
    def test_follow_approaches_an_offset_marker(self):
        """The real detector + real behavior close the loop in simulation.

        The follow controller only sees rendered JPEGs; if signs anywhere in
        the chain (camera x, steering direction, yaw sign) disagreed, the
        rover would diverge instead of approaching.
        """

        simulation = FerretSimulation(marker_xy=(2.0, 0.4))
        vision = ArucoVision(target_id=7)
        follow = FollowController()

        dt = 1.0 / 15.0
        initial = math.hypot(
            simulation.marker_x - simulation.x,
            simulation.marker_y - simulation.y,
        )

        for _ in range(600):  # 40 simulated seconds
            result = vision.detect_jpeg(simulation.render_jpeg())
            proposal = follow.update(
                result["visible"],
                result["x"],
                result["size"],
            )

            simulation.command(proposal.throttle, proposal.steering)
            simulation.step(dt)

        final = math.hypot(
            simulation.marker_x - simulation.x,
            simulation.marker_y - simulation.y,
        )

        self.assertLess(final, initial * 0.5)

        view = simulation.observe_marker()
        self.assertIsNotNone(view)


if __name__ == "__main__":
    unittest.main()
