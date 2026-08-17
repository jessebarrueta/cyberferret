import unittest

from cyberferret_safety import (
    AUTONOMY_LINK_TIMEOUT_S,
    AUTONOMY_MAX_DURATION_S,
    MANUAL_LINK_TIMEOUT_S,
    REASON_AUTONOMY_EXPIRED,
    REASON_CLEAR,
    REASON_EMERGENCY,
    REASON_LINK_LOST,
    REASON_OBSTACLE,
    SafetyInputs,
    arbitrate,
)


def decide(**kwargs):
    return arbitrate(SafetyInputs(**kwargs))


class TestManualMode(unittest.TestCase):
    def test_fresh_link_is_clear(self):
        decision = decide(mode="MANUAL", control_link_age_s=0.1)
        self.assertTrue(decision.clear)
        self.assertEqual(decision.reason, REASON_CLEAR)

    def test_never_heard_from_anyone_is_lost(self):
        decision = decide(mode="MANUAL")
        self.assertFalse(decision.clear)
        self.assertEqual(decision.reason, REASON_LINK_LOST)

    def test_stale_link_stops(self):
        decision = decide(
            mode="MANUAL",
            control_link_age_s=MANUAL_LINK_TIMEOUT_S + 0.01,
        )
        self.assertTrue(decision.link_stop)
        self.assertFalse(decision.clear)


class TestFollowMode(unittest.TestCase):
    def test_brief_dropout_tolerated(self):
        # A hiccup longer than the manual timeout but within the autonomy
        # tolerance must not abort a run...
        decision = decide(
            mode="FOLLOW",
            control_link_age_s=1.0,
            autonomy_age_s=10.0,
        )
        self.assertTrue(decision.clear)

        # ...but the HUD must still show the link as degraded.
        self.assertFalse(decision.control_link_ok)

    def test_real_disconnect_stops_and_disarms(self):
        decision = decide(
            mode="FOLLOW",
            control_link_age_s=AUTONOMY_LINK_TIMEOUT_S + 0.01,
            autonomy_age_s=10.0,
        )
        self.assertFalse(decision.clear)
        self.assertEqual(decision.reason, REASON_LINK_LOST)
        self.assertTrue(decision.disarm_autonomy)

    def test_autonomy_time_limit(self):
        decision = decide(
            mode="FOLLOW",
            control_link_age_s=0.1,
            autonomy_age_s=AUTONOMY_MAX_DURATION_S + 1.0,
        )
        self.assertFalse(decision.clear)
        self.assertEqual(decision.reason, REASON_AUTONOMY_EXPIRED)
        self.assertTrue(decision.disarm_autonomy)

    def test_time_limit_can_be_disabled(self):
        decision = arbitrate(
            SafetyInputs(
                mode="FOLLOW",
                control_link_age_s=0.1,
                autonomy_age_s=999999.0,
            ),
            autonomy_max_duration_s=None,
        )
        self.assertTrue(decision.clear)

    def test_time_limit_does_not_apply_to_manual(self):
        decision = decide(
            mode="MANUAL",
            control_link_age_s=0.1,
            autonomy_age_s=AUTONOMY_MAX_DURATION_S + 1.0,
        )
        self.assertTrue(decision.clear)


class TestEmergencyStop(unittest.TestCase):
    def test_latched_estop_beats_everything(self):
        decision = decide(
            mode="FOLLOW",
            emergency_stop_latched=True,
            control_link_age_s=999.0,
            autonomy_age_s=999999.0,
            obstacle_stop=True,
        )
        self.assertEqual(decision.reason, REASON_EMERGENCY)
        self.assertFalse(decision.clear)
        self.assertTrue(decision.disarm_autonomy)

    def test_estop_alone(self):
        decision = decide(
            mode="MANUAL",
            emergency_stop_latched=True,
            control_link_age_s=0.1,
        )
        self.assertEqual(decision.reason, REASON_EMERGENCY)


class TestObstacle(unittest.TestCase):
    def test_obstacle_stops_but_does_not_disarm(self):
        # An obstacle reflex is transient: FOLLOW may continue once the path
        # clears. It must stop motion but not require a human re-arm.
        decision = decide(
            mode="FOLLOW",
            control_link_age_s=0.1,
            autonomy_age_s=1.0,
            obstacle_stop=True,
        )
        self.assertEqual(decision.reason, REASON_OBSTACLE)
        self.assertFalse(decision.clear)
        self.assertFalse(decision.disarm_autonomy)

    def test_obstacle_ranks_below_estop(self):
        decision = decide(
            mode="MANUAL",
            emergency_stop_latched=True,
            control_link_age_s=0.1,
            obstacle_stop=True,
        )
        self.assertEqual(decision.reason, REASON_EMERGENCY)


class TestPrecedence(unittest.TestCase):
    def test_full_ordering(self):
        # Build inputs that trigger everything, then peel conditions off one
        # at a time and confirm the reason follows the documented precedence.
        decision = decide(
            mode="FOLLOW",
            emergency_stop_latched=True,
            control_link_age_s=999.0,
            autonomy_age_s=999999.0,
            obstacle_stop=True,
        )
        self.assertEqual(decision.reason, REASON_EMERGENCY)

        decision = decide(
            mode="FOLLOW",
            control_link_age_s=999.0,
            autonomy_age_s=999999.0,
            obstacle_stop=True,
        )
        self.assertEqual(decision.reason, REASON_OBSTACLE)

        decision = decide(
            mode="FOLLOW",
            control_link_age_s=999.0,
            autonomy_age_s=999999.0,
        )
        self.assertEqual(decision.reason, REASON_LINK_LOST)

        decision = decide(
            mode="FOLLOW",
            control_link_age_s=0.1,
            autonomy_age_s=999999.0,
        )
        self.assertEqual(decision.reason, REASON_AUTONOMY_EXPIRED)

        decision = decide(
            mode="FOLLOW",
            control_link_age_s=0.1,
            autonomy_age_s=1.0,
        )
        self.assertEqual(decision.reason, REASON_CLEAR)


if __name__ == "__main__":
    unittest.main()
