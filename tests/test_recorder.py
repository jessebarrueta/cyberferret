import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from cyberferret_recorder import ExperienceRecorder
from cyberferret_state import FerretState


class FakeCamera:
    def __init__(self):
        self.sequence = 0

    def get_latest(self):
        self.sequence += 1
        return {
            "sequence": self.sequence,
            "jpeg": b"\xff\xd8fake-jpeg\xff\xd9",
            "timestamp": time.time(),
            "monotonic_timestamp": time.monotonic(),
            "width": 640,
            "height": 480,
        }


class CountingLock:
    """A lock that counts acquisitions, to prove the recorder uses it."""

    def __init__(self):
        self._lock = threading.Lock()
        self.acquisitions = 0

    def __enter__(self):
        self._lock.acquire()
        self.acquisitions += 1
        return self

    def __exit__(self, *exc):
        self._lock.release()
        return False


class TestExperienceRecorder(unittest.TestCase):
    def _run_recorder(self, lock=None, cycles=3):
        with tempfile.TemporaryDirectory() as root:
            recorder = ExperienceRecorder(
                camera=FakeCamera(),
                state=FerretState(),
                state_lock=lock,
                interval_s=0.01,
                root=root,
            )

            recorder.start()
            time.sleep(0.01 * cycles + 0.05)
            recorder.stop()

            session = recorder.session_dir
            observations = (
                (session / "observations.jsonl").read_text().splitlines()
            )
            frames = sorted((session / "frames").iterdir())

            return observations, frames

    def test_records_frames_and_observations(self):
        observations, frames = self._run_recorder()

        self.assertGreater(len(observations), 0)
        self.assertEqual(len(observations), len(frames))

        record = json.loads(observations[0])
        self.assertEqual(record["sequence"], 1)
        self.assertEqual(record["frame"], "frames/000001.jpg")
        self.assertIn("safety", record)
        self.assertIn("intent", record)
        self.assertIn("body", record)

    def test_recent_events_not_duplicated_into_records(self):
        observations, _frames = self._run_recorder()

        record = json.loads(observations[0])
        self.assertNotIn("recent", record["events"])

    def test_snapshots_are_taken_under_the_state_lock(self):
        lock = CountingLock()
        observations, _frames = self._run_recorder(lock=lock)

        self.assertGreaterEqual(lock.acquisitions, len(observations))

    def test_unwritable_root_fails_loudly_but_does_not_raise(self):
        recorder = ExperienceRecorder(
            camera=FakeCamera(),
            state=FerretState(),
            root="/proc/definitely-not-writable",
        )

        recorder.start()  # must not raise
        self.assertFalse(recorder._running)


if __name__ == "__main__":
    unittest.main()
