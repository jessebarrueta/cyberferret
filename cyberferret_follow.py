"""Marker-follow behavior.

A behavior proposes intent from an observation. It has no authority over the
body: safety arbitration sits between this and the control loop, and may veto
anything proposed here.

Pure and hardware-free. `update()` is a function of the observation plus the
controller's own filter state, so a whole approach can be replayed in a test.
"""

from dataclasses import dataclass

from cyberferret_control import clamp, low_pass


STEERING_GAIN = 0.75
STEERING_DEADBAND = 0.10
FILTER_ALPHA = 0.28
ACQUIRE_FRAMES = 2

# Apparent marker width, as a fraction of frame width.
TARGET_SIZE = 0.23
SLOW_SIZE = 0.17

MAX_THROTTLE = 0.07
SLOW_THROTTLE = 0.03


@dataclass(frozen=True)
class FollowOutput:
    throttle: float = 0.0
    steering: float = 0.0
    acquired: bool = False
    filtered_x: float | None = None
    filtered_size: float | None = None


class FollowController:
    def __init__(
        self,
        steering_gain=STEERING_GAIN,
        steering_deadband=STEERING_DEADBAND,
        filter_alpha=FILTER_ALPHA,
        acquire_frames=ACQUIRE_FRAMES,
        target_size=TARGET_SIZE,
        slow_size=SLOW_SIZE,
        max_throttle=MAX_THROTTLE,
        slow_throttle=SLOW_THROTTLE,
    ):
        self.steering_gain = steering_gain
        self.steering_deadband = steering_deadband
        self.filter_alpha = filter_alpha
        self.acquire_frames = acquire_frames
        self.target_size = target_size
        self.slow_size = slow_size
        self.max_throttle = max_throttle
        self.slow_throttle = slow_throttle

        self.reset()

    def reset(self):
        self.filtered_x = None
        self.filtered_size = None
        self.visible_frames = 0

    def update(self, visible, target_x, target_size):
        """Propose intent from the current visual observation.

        Losing the target is not an error condition; it simply produces a
        zero-motion proposal and forgets the filter, so reacquiring starts
        from the new measurement instead of a stale one.
        """

        if not visible or target_x is None or target_size is None:
            self.reset()
            return FollowOutput()

        self.visible_frames += 1

        self.filtered_x = low_pass(
            self.filtered_x,
            target_x,
            self.filter_alpha,
        )

        self.filtered_size = low_pass(
            self.filtered_size,
            target_size,
            self.filter_alpha,
        )

        acquired = self.visible_frames >= self.acquire_frames

        steering = 0.0
        throttle = 0.0

        if acquired:
            if abs(self.filtered_x) > self.steering_deadband:
                steering = clamp(
                    self.filtered_x * self.steering_gain,
                    -1.0,
                    1.0,
                )

            if self.filtered_size >= self.target_size:
                throttle = 0.0
            elif self.filtered_size >= self.slow_size:
                throttle = self.slow_throttle
            else:
                throttle = self.max_throttle

        return FollowOutput(
            # FOLLOW never reverses. Backing up toward something it cannot see
            # is not a maneuver this behavior is allowed to propose.
            throttle=max(0.0, throttle),
            steering=steering,
            acquired=acquired,
            filtered_x=self.filtered_x,
            filtered_size=self.filtered_size,
        )
