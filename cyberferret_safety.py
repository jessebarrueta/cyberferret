"""Deterministic safety arbitration.

Safety is an authority boundary, not a behavior. This module is a pure function
from "what do we know right now" to "what is Cyber Ferret allowed to do", with
no hardware, no clock reads and no global state, so every rule can be tested
exhaustively on a laptop.

Precedence, highest first:

    EMERGENCY STOP      latched; a human pressed SPACE
    OBSTACLE            a reflex vetoed forward motion
    CONTROL LINK LOST   the commanding browser stopped talking to us
    AUTONOMY TIME LIMIT autonomy has been running unattended for too long
    CLEAR
"""

from dataclasses import dataclass


# A human driving manually needs a tight loop; half a second of silence means
# the link is gone and the vehicle should coast to neutral.
MANUAL_LINK_TIMEOUT_S = 0.5

# Autonomy does not need a browser in order to think, but it does need one in
# order to be stoppable. This is deliberately longer than the manual timeout so
# a brief Wi-Fi hiccup does not abort a run, and deliberately finite so a real
# disconnect cannot leave the vehicle driving with no remote stop.
AUTONOMY_LINK_TIMEOUT_S = 3.0

# Upper bound on a single continuous autonomous run. Set to None to disable.
AUTONOMY_MAX_DURATION_S = 300.0

REASON_EMERGENCY = "EMERGENCY STOP"
REASON_OBSTACLE = "OBSTACLE"
REASON_LINK_LOST = "CONTROL LINK LOST"
REASON_AUTONOMY_EXPIRED = "AUTONOMY TIME LIMIT"
REASON_CLEAR = "CLEAR"


@dataclass(frozen=True)
class SafetyInputs:
    mode: str = "MANUAL"

    # True once SPACE has been pressed and until a human explicitly clears it.
    emergency_stop_latched: bool = False

    # Seconds since the last control message from a browser. A large value
    # means "never heard from anyone", which is correctly treated as lost.
    control_link_age_s: float = float("inf")

    # Seconds the current autonomous run has been armed, or None in MANUAL.
    autonomy_age_s: float | None = None

    # Reserved for the incoming ToF sensors; already wired end to end so the
    # obstacle reflex only has to set this flag.
    obstacle_stop: bool = False


@dataclass(frozen=True)
class SafetyDecision:
    control_link_ok: bool
    emergency_stop: bool
    obstacle_stop: bool
    link_stop: bool
    autonomy_expired: bool
    reason: str

    @property
    def clear(self):
        return not (
            self.emergency_stop
            or self.obstacle_stop
            or self.link_stop
            or self.autonomy_expired
        )

    @property
    def disarm_autonomy(self):
        """Should an armed autonomous mode be dropped back to MANUAL?

        Every stop that is not a transient obstacle reflex requires a human to
        deliberately re-arm autonomy. Coming back from a stop should never be
        something that happens on its own while nobody is watching.
        """

        return (
            self.emergency_stop
            or self.link_stop
            or self.autonomy_expired
        )


def link_timeout_for_mode(mode):
    return (
        AUTONOMY_LINK_TIMEOUT_S
        if mode == "FOLLOW"
        else MANUAL_LINK_TIMEOUT_S
    )


def arbitrate(inputs, autonomy_max_duration_s=AUTONOMY_MAX_DURATION_S):
    # "Link OK" always means the tight manual standard, so the HUD reports the
    # honest state of the connection rather than the looser autonomy tolerance.
    control_link_ok = inputs.control_link_age_s <= MANUAL_LINK_TIMEOUT_S

    link_stop = (
        inputs.control_link_age_s
        > link_timeout_for_mode(inputs.mode)
    )

    autonomy_expired = (
        inputs.mode == "FOLLOW"
        and autonomy_max_duration_s is not None
        and inputs.autonomy_age_s is not None
        and inputs.autonomy_age_s > autonomy_max_duration_s
    )

    if inputs.emergency_stop_latched:
        reason = REASON_EMERGENCY
    elif inputs.obstacle_stop:
        reason = REASON_OBSTACLE
    elif link_stop:
        reason = REASON_LINK_LOST
    elif autonomy_expired:
        reason = REASON_AUTONOMY_EXPIRED
    else:
        reason = REASON_CLEAR

    return SafetyDecision(
        control_link_ok=control_link_ok,
        emergency_stop=inputs.emergency_stop_latched,
        obstacle_stop=inputs.obstacle_stop,
        link_stop=link_stop,
        autonomy_expired=autonomy_expired,
        reason=reason,
    )
