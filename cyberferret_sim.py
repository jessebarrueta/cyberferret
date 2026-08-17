"""A laptop stand-in for Cyber Ferret's body.

This is not a physics engine. It is a crude bicycle model plus a pinhole
camera, good enough to render a real ArUco marker into a real JPEG so the real
detector, the real follow behavior, and the real safety arbitration all run
unmodified with no hardware attached.

Enable with CYBERFERRET_SIM=1.

The point is to be able to iterate on behavior without putting a physical
vehicle at risk, not to predict how the physical vehicle will actually behave.
Anything learned here still has to be confirmed with the wheels elevated.
"""

import math
import threading
import time
from io import BytesIO

import cv2
import numpy as np
from PIL import Image

import cyberferret_calibration as calibration


WHEELBASE_M = 0.25
MAX_STEER_RAD = math.radians(25.0)

# Metres per second at throttle 1.0. Roughly matched to how the real vehicle
# behaves at the conservative throttle values the application actually uses.
SPEED_SCALE_MPS = 2.0

CAMERA_HFOV_RAD = math.radians(62.2)
MARKER_WIDTH_M = 0.15

MARKER_ID = 7
MARKER_DICTIONARY = cv2.aruco.DICT_4X4_50


def _wrap_angle(radians):
    return (radians + math.pi) % (2 * math.pi) - math.pi


class FerretSimulation:
    """Rover pose, a marker sitting in the world, and a camera looking at it."""

    def __init__(self, marker_xy=(2.0, 0.35), size=(640, 480)):
        self.width, self.height = size

        self.x = 0.0
        self.y = 0.0
        self.heading = 0.0

        self.marker_x, self.marker_y = marker_xy

        self.throttle = 0.0
        self.steering = 0.0

        self._lock = threading.Lock()
        self._marker = self._render_marker()

    @staticmethod
    def _render_marker(pixels=240):
        dictionary = cv2.aruco.getPredefinedDictionary(MARKER_DICTIONARY)
        marker = cv2.aruco.generateImageMarker(
            dictionary,
            MARKER_ID,
            pixels,
        )

        # Real printed markers carry a quiet zone; without one the detector
        # rejects a marker that runs to the edge of the pasted region.
        margin = pixels // 5
        canvas = np.full(
            (pixels + margin * 2, pixels + margin * 2),
            255,
            dtype=np.uint8,
        )
        canvas[margin:margin + pixels, margin:margin + pixels] = marker

        return canvas

    def command(self, throttle, steering):
        with self._lock:
            self.throttle = throttle
            self.steering = steering

    def step(self, dt):
        with self._lock:
            throttle = self.throttle
            steering = self.steering

        speed = throttle * SPEED_SCALE_MPS
        steer_rad = steering * MAX_STEER_RAD

        # Positive steering is a physical right turn, which decreases heading
        # in a conventional counter-clockwise-positive world frame.
        yaw_rate = -(speed / WHEELBASE_M) * math.tan(steer_rad)

        self.heading = _wrap_angle(self.heading + yaw_rate * dt)
        self.x += speed * math.cos(self.heading) * dt
        self.y += speed * math.sin(self.heading) * dt

    def observe_marker(self):
        """Where the marker appears, in the same units the vision layer uses."""

        dx = self.marker_x - self.x
        dy = self.marker_y - self.y

        distance = math.hypot(dx, dy)
        if distance < 0.05:
            return None

        bearing = _wrap_angle(math.atan2(dy, dx) - self.heading)
        half_fov = CAMERA_HFOV_RAD / 2.0

        if abs(bearing) > half_fov:
            return None

        size_fraction = MARKER_WIDTH_M / (
            2.0 * distance * math.tan(half_fov)
        )

        return {
            # Camera x is +1 at the right edge; a positive bearing is to
            # the left, hence the sign flip.
            "x": -bearing / half_fov,
            "size": size_fraction,
            "distance": distance,
        }

    def render_jpeg(self, quality=70):
        frame = np.full(
            (self.height, self.width, 3),
            215,
            dtype=np.uint8,
        )
        frame[self.height // 2:, :] = 170

        view = self.observe_marker()

        if view is not None:
            pixels = int(view["size"] * self.width)

            if pixels >= 12:
                scaled = cv2.resize(
                    self._marker,
                    (pixels, pixels),
                    interpolation=cv2.INTER_NEAREST,
                )

                center_x = int((view["x"] + 1.0) / 2.0 * self.width)
                center_y = self.height // 2

                left = center_x - pixels // 2
                top = center_y - pixels // 2

                # Clip against the frame rather than refusing to draw, so a
                # marker leaving the edge behaves the way a real one does.
                src_left = max(0, -left)
                src_top = max(0, -top)
                dst_left = max(0, left)
                dst_top = max(0, top)

                dst_right = min(self.width, left + pixels)
                dst_bottom = min(self.height, top + pixels)

                if dst_right > dst_left and dst_bottom > dst_top:
                    patch = scaled[
                        src_top:src_top + (dst_bottom - dst_top),
                        src_left:src_left + (dst_right - dst_left),
                    ]
                    frame[
                        dst_top:dst_bottom,
                        dst_left:dst_right,
                    ] = patch[:, :, None]

        image = Image.fromarray(frame)
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=quality)
        return buffer.getvalue()


class SimDrive:
    """Drop-in replacement for CyberFerretDrive that moves a simulated body."""

    def __init__(self, simulation):
        self.simulation = simulation
        self._throttle = 0.0
        self._steering = 0.0
        self._steering_deg = calibration.STEERING_CENTER_DEG
        self._throttle_us = calibration.ESC_NEUTRAL_US

    def _push(self):
        self.simulation.command(self._throttle, self._steering)

    def steer(self, amount):
        self._steering = max(-1.0, min(1.0, float(amount)))
        self._steering_deg = calibration.steering_to_degrees(self._steering)
        self._push()

    def center(self):
        self.steer(0.0)

    def throttle(self, amount):
        self._throttle = calibration.normalize_throttle(amount)
        self._throttle_us = calibration.throttle_to_pulse_us(self._throttle)
        self._push()

    def forward(self, speed):
        self.throttle(abs(float(speed)))

    def reverse(self, speed):
        self.throttle(-abs(float(speed)))

    def stop(self):
        self.throttle(0.0)

    def adjust_throttle(self, delta):
        self.throttle(self._throttle + delta)

    def adjust_steering(self, delta):
        self.steer(self._steering + delta)

    def status(self):
        return {
            "steering": round(self._steering, 3),
            "steering_deg": round(self._steering_deg, 1),
            "throttle": round(self._throttle, 3),
            "throttle_us": self._throttle_us,
        }

    def shutdown(self):
        self.stop()
        self.center()


class SimCamera:
    """Drop-in replacement for CyberFerretCamera that renders the simulation."""

    def __init__(
        self,
        simulation,
        size=(640, 480),
        jpeg_quality=70,
        capture_fps=15,
    ):
        self.simulation = simulation
        self.size = size
        self.jpeg_quality = jpeg_quality
        self.capture_fps = capture_fps

        self._latest = None
        self._sequence = 0
        self._fps = 0.0
        self._lock = threading.Lock()
        self._running = False
        self._thread = None

    @property
    def fps(self):
        with self._lock:
            return self._fps

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._capture_loop,
            name="sim-camera",
            daemon=True,
        )
        self._thread.start()

    def _capture_loop(self):
        interval = 1.0 / self.capture_fps
        previous = time.monotonic()

        while self._running:
            started = time.monotonic()

            self.simulation.step(started - previous)
            previous = started

            jpeg = self.simulation.render_jpeg(self.jpeg_quality)

            with self._lock:
                self._sequence += 1
                self._latest = {
                    "sequence": self._sequence,
                    "jpeg": jpeg,
                    "timestamp": time.time(),
                    "monotonic_timestamp": started,
                    "width": self.size[0],
                    "height": self.size[1],
                }
                self._fps = self.capture_fps

            elapsed = time.monotonic() - started
            time.sleep(max(0.0, interval - elapsed))

    def get_latest(self):
        with self._lock:
            return self._latest

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)


def build():
    """Return (drive, camera) backed by a shared simulation."""

    simulation = FerretSimulation()
    return SimDrive(simulation), SimCamera(simulation)
