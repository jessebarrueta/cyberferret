import unittest

from cyberferret_entity import (
    CyberFerretEntity,
    FOLLOW,
    INVESTIGATE,
    WAIT,
)


def event(event_type):
    return {
        "type": event_type,
        "timestamp": 0.0,
        "monotonic": 0.0,
        "data": {},
    }


class TestCyberFerretEntity(unittest.TestCase):
    def test_unsafe_always_recommends_wait(self):
        entity = CyberFerretEntity()

        decision = entity.choose_behavior(
            target_visible=True,
            target_size=0.10,
            safety_clear=False,
            mode="FOLLOW",
        )

        self.assertEqual(decision.behavior, WAIT)
        self.assertEqual(decision.confidence, 1.0)

    def test_target_acquired_changes_drives(self):
        entity = CyberFerretEntity()

        curiosity = entity.drives.curiosity
        social = entity.drives.social_interest
        boredom = entity.drives.boredom

        entity.consume_events([event("TARGET_ACQUIRED")])

        self.assertGreater(entity.drives.curiosity, curiosity)
        self.assertGreater(entity.drives.social_interest, social)
        self.assertLess(entity.drives.boredom, boredom)

    def test_bad_event_increases_caution(self):
        entity = CyberFerretEntity()

        caution = entity.drives.caution
        confidence = entity.drives.confidence

        entity.consume_events([event("OBSTACLE_STOP")])

        self.assertGreater(entity.drives.caution, caution)
        self.assertLess(entity.drives.confidence, confidence)

    def test_drive_values_remain_bounded(self):
        entity = CyberFerretEntity()

        entity.consume_events(
            [event("OBSTACLE_STOP")] * 100
            + [event("TARGET_ACQUIRED")] * 100
        )

        for value in entity.snapshot()["drives"].values():
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 1.0)

    def test_visible_target_prefers_active_behavior(self):
        entity = CyberFerretEntity()

        decision = entity.choose_behavior(
            target_visible=True,
            target_size=0.10,
            safety_clear=True,
            mode="MANUAL",
        )

        self.assertIn(decision.behavior, {FOLLOW, INVESTIGATE})

    def test_no_target_defaults_to_wait(self):
        entity = CyberFerretEntity()

        decision = entity.choose_behavior(
            target_visible=False,
            target_size=None,
            safety_clear=True,
            mode="MANUAL",
        )

        self.assertEqual(decision.behavior, WAIT)

    def test_boredom_increases_with_time(self):
        entity = CyberFerretEntity()

        before = entity.drives.boredom
        entity.tick(10.0)

        self.assertGreater(entity.drives.boredom, before)

    def test_caution_decays_toward_baseline(self):
        entity = CyberFerretEntity()

        entity.consume_events([event("EMERGENCY_STOP")])

        elevated = entity.drives.caution
        entity.tick(10.0)

        self.assertLess(entity.drives.caution, elevated)
        self.assertGreaterEqual(entity.drives.caution, 0.30)

    def test_snapshot_is_serializable_shape(self):
        entity = CyberFerretEntity()

        snapshot = entity.snapshot()

        self.assertIn("drives", snapshot)
        self.assertIn("decision", snapshot)
        self.assertIn("reason", snapshot["decision"])


if __name__ == "__main__":
    unittest.main()
