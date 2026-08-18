import unittest

from cyberferret_state import FerretState


class TestEntityState(unittest.TestCase):
    def test_entity_is_exposed_in_serialized_state(self):
        state = FerretState()

        state.entity.curiosity = 0.73
        state.entity.recommended_behavior = "INVESTIGATE"
        state.entity.decision_reason = "Science, apparently."

        snapshot = state.to_dict()

        self.assertIn("entity", snapshot)
        self.assertEqual(snapshot["entity"]["curiosity"], 0.73)
        self.assertEqual(
            snapshot["entity"]["recommended_behavior"],
            "INVESTIGATE",
        )
        self.assertEqual(
            snapshot["entity"]["decision_reason"],
            "Science, apparently.",
        )

    def test_recent_events_flag_does_not_remove_entity(self):
        state = FerretState()
        snapshot = state.to_dict(include_recent_events=False)

        self.assertIn("entity", snapshot)
        self.assertNotIn("recent", snapshot["events"])


if __name__ == "__main__":
    unittest.main()
