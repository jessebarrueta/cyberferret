import unittest

import cyberferret_safety as safety
from cyberferret_events import EventDetector
from cyberferret_state import FerretState


def types(emitted):
    return [event["type"] for event in emitted]


class TestEventDetector(unittest.TestCase):
    def setUp(self):
        self.detector = EventDetector(target_reached_size=0.23)
        self.state = FerretState()

        # Establish a baseline so later updates only report real changes.
        self.state.safety.reason = safety.REASON_CLEAR
        self.detector.update(self.state)

    def test_quiet_state_emits_nothing(self):
        self.assertEqual(self.detector.update(self.state), [])

    def test_mode_change(self):
        self.state.mode = "FOLLOW"
        emitted = types(self.detector.update(self.state))
        self.assertIn("MODE_CHANGED", emitted)
        self.assertIn("FOLLOW_STARTED", emitted)

        self.state.mode = "MANUAL"
        emitted = types(self.detector.update(self.state))
        self.assertIn("FOLLOW_STOPPED", emitted)

    def test_target_acquired_and_lost(self):
        self.state.observation.visual_target_visible = True
        self.state.observation.visual_target_id = 7
        emitted = types(self.detector.update(self.state))
        self.assertIn("TARGET_ACQUIRED", emitted)

        self.state.observation.visual_target_visible = False
        emitted = types(self.detector.update(self.state))
        self.assertIn("TARGET_LOST", emitted)

    def test_target_reached_uses_behavior_filtered_size(self):
        self.state.mode = "FOLLOW"
        self.state.observation.visual_target_visible = True
        self.state.intent.throttle = 0.0

        # Raw size is over the threshold but the filtered size the behavior
        # acted on is not: no TARGET_REACHED yet.
        self.state.observation.visual_target_size = 0.5
        self.state.behavior.follow_filtered_size = 0.20
        emitted = types(self.detector.update(self.state))
        self.assertNotIn("TARGET_REACHED", emitted)

        # Filtered size crosses: now the event agrees with the behavior.
        self.state.behavior.follow_filtered_size = 0.24
        emitted = types(self.detector.update(self.state))
        self.assertIn("TARGET_REACHED", emitted)

        # And it fires once, not every frame.
        emitted = types(self.detector.update(self.state))
        self.assertNotIn("TARGET_REACHED", emitted)

    def test_safety_reason_events(self):
        self.state.safety.reason = safety.REASON_EMERGENCY
        emitted = types(self.detector.update(self.state))
        self.assertIn("EMERGENCY_STOP", emitted)

        self.state.safety.reason = safety.REASON_LINK_LOST
        emitted = types(self.detector.update(self.state))
        self.assertIn("CONTROL_LINK_LOST", emitted)

        self.state.safety.reason = safety.REASON_AUTONOMY_EXPIRED
        emitted = types(self.detector.update(self.state))
        self.assertIn("AUTONOMY_EXPIRED", emitted)

        self.state.safety.reason = safety.REASON_CLEAR
        emitted = types(self.detector.update(self.state))
        self.assertIn("SAFETY_CLEAR", emitted)

    def test_turn_events(self):
        self.state.intent.steering = -0.5
        emitted = types(self.detector.update(self.state))
        self.assertIn("TURN_LEFT_STARTED", emitted)

        self.state.intent.steering = 0.0
        emitted = types(self.detector.update(self.state))
        self.assertIn("TURN_STOPPED", emitted)


if __name__ == "__main__":
    unittest.main()
