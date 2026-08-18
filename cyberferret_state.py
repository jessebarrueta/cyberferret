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
    """What Cyber Ferret believes it senses, before any behavior filtering."""

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
class BehaviorState:
    """What the active behavior currently believes.

    Kept separate from ObservationState: the raw measurement and the filtered
    quantity a controller actually acted on are different facts, and a causal
    trace needs both.
    """

    follow_acquired: bool = False
    follow_filtered_x: float | None = None
    follow_filtered_size: float | None = None


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

    # Latched: stays set until a human explicitly clears it.
    emergency_stop: bool = False

    obstacle_stop: bool = False

    # The commanding browser stopped talking to us.
    link_stop: bool = True

    # A single autonomous run exceeded its permitted duration.
    autonomy_expired: bool = False

    reason: str = "WAITING FOR CONTROL"

    autonomy_age_s: float | None = None
    autonomy_limit_s: float | None = None

    @property
    def clear(self):
        return not (
            self.emergency_stop
            or self.obstacle_stop
            or self.link_stop
            or self.autonomy_expired
        )


@dataclass
class EventState:
    sequence: int = 0
    last_type: str | None = None
    last_timestamp: float | None = None
    recent: list = field(default_factory=list)


@dataclass
class EntityState:
    """Observable snapshot of the slow AI entity.

    Advisory only: nothing in this state directly controls actuators.
    """

    curiosity: float = 0.60
    caution: float = 0.30
    social_interest: float = 0.45
    confidence: float = 0.50
    energy: float = 1.00
    boredom: float = 0.10

    last_event_type: str | None = None

    recommended_behavior: str = "WAIT"
    decision_confidence: float = 1.0
    decision_reason: str = "No meaningful stimulus yet."
    scores: dict = field(default_factory=dict)


@dataclass
class FerretState:
    intent: ControlIntent = field(default_factory=ControlIntent)
    body: BodyState = field(default_factory=BodyState)
    observation: ObservationState = field(default_factory=ObservationState)
    behavior: BehaviorState = field(default_factory=BehaviorState)
    environment: EnvironmentState = field(default_factory=EnvironmentState)
    safety: SafetyState = field(default_factory=SafetyState)
    events: EventState = field(default_factory=EventState)
    entity: EntityState = field(default_factory=EntityState)
    mode: str = "MANUAL"
    loop_hz: float = 0.0
    camera_fps: float = 0.0
    vision_hz: float = 0.0
    started_at: float = field(default_factory=time.monotonic)

    def to_dict(self, include_recent_events=True):
        data = asdict(self)
        data["uptime_s"] = round(time.monotonic() - self.started_at, 1)
        data["safety"]["clear"] = self.safety.clear

        if not include_recent_events:
            # The event ring is HUD convenience. Writing it into every
            # recorded frame would store each event about twenty times over.
            data["events"].pop("recent", None)

        return data
