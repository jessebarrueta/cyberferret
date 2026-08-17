import json
import os
import threading
import time
from pathlib import Path


DEFAULT_ROOT = os.environ.get(
    "CYBERFERRET_DATA",
    str(Path.home() / "cyberferret-data" / "sessions"),
)


class ExperienceRecorder:
    def __init__(
        self,
        camera,
        state,
        interval_s=0.25,
        root=DEFAULT_ROOT,
    ):
        self.camera = camera
        self.state = state
        self.interval_s = interval_s
        self.root = Path(root)

        self._running = False
        self._thread = None
        self._session_dir = None
        self._frames_dir = None
        self._observations_path = None
        self._sequence = 0
        self._started_monotonic = 0.0
        self._failed = False

    @property
    def session_dir(self):
        return self._session_dir

    def start(self):
        if self._running:
            return

        stamp = time.strftime("%Y-%m-%d_%H-%M-%S")
        self._session_dir = self.root / stamp
        self._frames_dir = self._session_dir / "frames"

        try:
            self._frames_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            # A rover that cannot write its diary should still drive.
            print(f"[RECORDER] cannot create {self._frames_dir}: {exc}")
            self._failed = True
            return

        self._observations_path = self._session_dir / "observations.jsonl"

        self._sequence = 0
        self._started_monotonic = time.monotonic()
        self._running = True
        self._failed = False
        self._thread = threading.Thread(
            target=self._loop,
            name="recorder",
            daemon=True,
        )
        self._thread.start()

        print(f"Recording session: {self._session_dir}")

    def _write_record(self):
        frame = self.camera.get_latest()

        if frame is None:
            return

        self._sequence += 1
        frame_name = f"{self._sequence:06d}.jpg"
        frame_path = self._frames_dir / frame_name
        frame_path.write_bytes(frame["jpeg"])

        snapshot = self.state.to_dict(include_recent_events=False)
        record = {
            "sequence": self._sequence,
            "session_time_s": round(
                time.monotonic() - self._started_monotonic,
                3,
            ),
            "timestamp": time.time(),
            "frame": f"frames/{frame_name}",
            **snapshot,
        }

        with self._observations_path.open("a") as f:
            f.write(json.dumps(record) + "\n")

    def _loop(self):
        while self._running:
            started = time.monotonic()

            try:
                self._write_record()
            except OSError as exc:
                # Out of space, card pulled, permissions changed. Stop
                # recording loudly rather than dying silently mid-drive.
                print(f"[RECORDER] write failed, stopping: {exc}")
                self._failed = True
                self._running = False
                break

            elapsed = time.monotonic() - started
            time.sleep(max(0.0, self.interval_s - elapsed))

    def stop(self):
        if not self._running:
            return
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
        print("Recording stopped.")
