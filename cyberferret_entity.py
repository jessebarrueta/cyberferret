"""Hardware-free AI entity state for Cyber Ferret.

The entity does not control actuators. It consumes semantic events and current
observations, maintains slow-changing internal drives, and recommends a
high-level behavior with an explanation. Deterministic behavior controllers
and safety arbitration remain responsible for physical action.
"""

from dataclasses import dataclass
from typing import Iterable

from cyberferret_control import clamp

WAIT = "WAIT"
FOLLOW = "FOLLOW"
INVESTIGATE = "INVESTIGATE"


@dataclass(frozen=True)
class EntityDecision:
    behavior: str
    confidence: float
    reason: str
    scores: dict[str, float]


@dataclass
class EntityDrives:
    curiosity: float = 0.60
    caution: float = 0.30
    social_interest: float = 0.45
    confidence: float = 0.50
    energy: float = 1.00
    boredom: float = 0.10

    def clamp_all(self):
        for name in (
            "curiosity",
            "caution",
            "social_interest",
            "confidence",
            "energy",
            "boredom",
        ):
            setattr(self, name, clamp(float(getattr(self, name)), 0.0, 1.0))


class CyberFerretEntity:
    """Slow, hardware-free entity model."""

    def __init__(self):
        self.drives = EntityDrives()
        self.last_event_type = None
        self.last_decision = EntityDecision(
            behavior=WAIT,
            confidence=1.0,
            reason="No meaningful stimulus yet.",
            scores={WAIT: 1.0, FOLLOW: 0.0, INVESTIGATE: 0.0},
        )

    def consume_events(self, events: Iterable[dict]):
        for event in events:
            event_type = event.get("type")
            self.last_event_type = event_type

            if event_type == "TARGET_ACQUIRED":
                self.drives.curiosity += 0.05
                self.drives.social_interest += 0.03
                self.drives.boredom -= 0.08
            elif event_type == "TARGET_LOST":
                self.drives.curiosity += 0.03
                self.drives.confidence -= 0.03
            elif event_type == "TARGET_REACHED":
                self.drives.confidence += 0.06
                self.drives.boredom -= 0.05
            elif event_type in {
                "OBSTACLE_STOP",
                "EMERGENCY_STOP",
                "CONTROL_LINK_LOST",
                "AUTONOMY_EXPIRED",
            }:
                self.drives.caution += 0.10
                self.drives.confidence -= 0.05
            elif event_type == "SAFETY_CLEAR":
                self.drives.caution -= 0.02
            elif event_type == "FOLLOW_STARTED":
                self.drives.boredom -= 0.03
            elif event_type == "FOLLOW_STOPPED":
                self.drives.boredom += 0.02

        self.drives.clamp_all()

    def tick(self, dt_s: float):
        dt_s = max(0.0, float(dt_s))
        self.drives.boredom += 0.006 * dt_s

        baseline_caution = 0.30
        if self.drives.caution > baseline_caution:
            self.drives.caution -= 0.004 * dt_s

        neutral_confidence = 0.50
        if self.drives.confidence > neutral_confidence:
            self.drives.confidence -= 0.002 * dt_s
        elif self.drives.confidence < neutral_confidence:
            self.drives.confidence += 0.002 * dt_s

        self.drives.clamp_all()

    def choose_behavior(
        self,
        *,
        target_visible: bool,
        target_size: float | None,
        safety_clear: bool,
        mode: str,
    ) -> EntityDecision:
        if not safety_clear:
            decision = EntityDecision(
                behavior=WAIT,
                confidence=1.0,
                reason="Safety is not clear; waiting outranks curiosity.",
                scores={WAIT: 1.0, FOLLOW: 0.0, INVESTIGATE: 0.0},
            )
            self.last_decision = decision
            return decision

        target_interest = 1.0 if target_visible else 0.0
        target_far = (
            1.0
            if target_visible and target_size is not None and target_size < 0.17
            else 0.0
        )

        wait_score = (
            0.25
            + self.drives.caution * 0.65
            + (1.0 - self.drives.energy) * 0.60
            - self.drives.boredom * 0.35
        )

        follow_score = (
            target_interest
            * (
                0.35
                + self.drives.social_interest * 0.45
                + self.drives.confidence * 0.20
            )
            - self.drives.caution * 0.20
        )

        investigate_score = (
            target_interest
            * (
                0.20
                + self.drives.curiosity * 0.50
                + self.drives.boredom * 0.30
                + target_far * 0.10
            )
            - self.drives.caution * 0.25
        )

        scores = {
            WAIT: clamp(wait_score, 0.0, 1.0),
            FOLLOW: clamp(follow_score, 0.0, 1.0),
            INVESTIGATE: clamp(investigate_score, 0.0, 1.0),
        }

        behavior = max(scores, key=scores.get)
        confidence = scores[behavior]

        if behavior == FOLLOW:
            reason = "A visible target plus social interest outweighs caution."
        elif behavior == INVESTIGATE:
            reason = "A visible target is interesting enough to investigate."
        else:
            reason = "No available stimulus currently outweighs waiting."

        if mode == "FOLLOW" and target_visible:
            reason += " Current FOLLOW mode is consistent with this recommendation."

        decision = EntityDecision(
            behavior=behavior,
            confidence=confidence,
            reason=reason,
            scores=scores,
        )
        self.last_decision = decision
        return decision

    def snapshot(self) -> dict:
        return {
            "drives": {
                "curiosity": self.drives.curiosity,
                "caution": self.drives.caution,
                "social_interest": self.drives.social_interest,
                "confidence": self.drives.confidence,
                "energy": self.drives.energy,
                "boredom": self.drives.boredom,
            },
            "last_event_type": self.last_event_type,
            "decision": {
                "behavior": self.last_decision.behavior,
                "confidence": self.last_decision.confidence,
                "reason": self.last_decision.reason,
                "scores": dict(self.last_decision.scores),
            },
        }
