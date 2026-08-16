import threading
import time
from io import BytesIO

from PIL import Image
from picamera2 import Picamera2


class CyberFerretCamera:
    def __init__(self, size=(640, 480), jpeg_quality=70, capture_fps=15):
        self.size = size
        self.jpeg_quality = jpeg_quality
        self.capture_fps = capture_fps

        self.camera = Picamera2()
        config = self.camera.create_video_configuration(
            main={"size": size, "format": "RGB888"}
        )
        self.camera.configure(config)

        self._latest_jpeg = None
        self._latest_sequence = 0
        self._latest_timestamp = 0.0
        self._latest_monotonic_timestamp = 0.0
        self._fps = 0.0
        self._lock = threading.Lock()
        self._running = False
        self._thread = None
        self._sequence = 0

    @property
    def fps(self):
        with self._lock:
            return self._fps

    def start(self):
        if self._running:
            return
        self.camera.start()
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def _capture_loop(self):
        frame_interval = 1.0 / self.capture_fps
        fps_started = time.monotonic()
        fps_frames = 0

        while self._running:
            started = time.monotonic()
            try:
                frame = self.camera.capture_array()
                image = Image.fromarray(frame)
                buffer = BytesIO()
                image.save(buffer, format="JPEG", quality=self.jpeg_quality)

                self._sequence += 1
                sequence = self._sequence
                jpeg = buffer.getvalue()
                epoch_timestamp = time.time()
                monotonic_timestamp = time.monotonic()

                fps_frames += 1
                fps_elapsed = monotonic_timestamp - fps_started
                new_fps = None
                if fps_elapsed >= 1.0:
                    new_fps = fps_frames / fps_elapsed
                    fps_frames = 0
                    fps_started = monotonic_timestamp

                with self._lock:
                    self._latest_sequence = sequence
                    self._latest_jpeg = jpeg
                    self._latest_timestamp = epoch_timestamp
                    self._latest_monotonic_timestamp = monotonic_timestamp
                    if new_fps is not None:
                        self._fps = new_fps

            except Exception as exc:
                if self._running:
                    print("Camera capture error:", exc)
                time.sleep(0.1)

            elapsed = time.monotonic() - started
            time.sleep(max(0.0, frame_interval - elapsed))

    def get_latest(self):
        with self._lock:
            if self._latest_jpeg is None:
                return None
            return {
                "sequence": self._latest_sequence,
                "jpeg": self._latest_jpeg,
                "timestamp": self._latest_timestamp,
                "monotonic_timestamp": self._latest_monotonic_timestamp,
                "width": self.size[0],
                "height": self.size[1],
            }

    def stop(self):
        if not self._running:
            return
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        try:
            self.camera.stop()
        except Exception:
            pass
