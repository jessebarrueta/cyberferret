from dataclasses import dataclass, asdict, field
import time


@dataclass
class ControlIntent:
    sequence: int = 0
    throttle: float = 0.0
    steering: float = 0.0
    source: str = "none"
    received_at: float = 0.0
    received_at_epoch: float = 0.0


@dataclass
class BodyState:
    sequence: int = 0
    commanded_throttle: float = 0.0
    commanded_steering: float = 0.0
    throttle_us: int = 1535
    steering_deg: float = 99.0
    updated_at: float = 0.0
    updated_at_epoch: float = 0.0
    actual_steering_deg: float | None = None
    ground_speed_mps: float | None = None
    battery_voltage: float | None = None
    current_amps: float | None = None
    power_watts: float | None = None


@dataclass
class ObservationState:
    sequence: int = 0
    captured_at: float = 0.0
    captured_at_epoch: float = 0.0
    width: int = 0
    height: int = 0
    visual_target_visible: bool = False
    visual_target_id: int | None = None
    visual_target_x: float | None = None
    visual_target_y: float | None = None
    visual_target_size: float | None = None


@dataclass
class EnvironmentState:
    front_distance_m: float | None = None
    rear_distance_m: float | None = None
    left_distance_m: float | None = None
    right_distance_m: float | None = None
    ground_distance_m: float | None = None
    heading_deg: float | None = None
    pitch_deg: float | None = None
    roll_deg: float | None = None
    yaw_rate_dps: float | None = None
    sound_direction_deg: float | None = None
    sound_level: float | None = None


@dataclass
class SafetyState:
    control_link_ok: bool = False
    emergency_stop: bool = False
    obstacle_stop: bool = False
    watchdog_stop: bool = False
    reason: str = "WAITING FOR CONTROL"

    @property
    def clear(self):
        return not (
            self.emergency_stop
            or self.obstacle_stop
            or self.watchdog_stop
        )


@dataclass
class EventState:
    sequence: int = 0
    last_type: str | None = None
    last_timestamp: float | None = None
    recent: list = field(default_factory=list)


@dataclass
class FerretState:
    intent: ControlIntent = field(default_factory=ControlIntent)
    body: BodyState = field(default_factory=BodyState)
    observation: ObservationState = field(default_factory=ObservationState)
    environment: EnvironmentState = field(default_factory=EnvironmentState)
    safety: SafetyState = field(default_factory=SafetyState)
    events: EventState = field(default_factory=EventState)
    mode: str = "MANUAL"
    loop_hz: float = 0.0
    camera_fps: float = 0.0
    vision_hz: float = 0.0
    started_at: float = field(default_factory=time.monotonic)

    def to_dict(self):
        data = asdict(self)
        data["uptime_s"] = round(time.monotonic() - self.started_at, 1)
        data["safety"]["clear"] = self.safety.clear
        return data
