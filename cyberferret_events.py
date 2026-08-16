import time
from collections import deque


class EventDetector:
    def __init__(self, max_events=100, target_reached_size=0.23):
        self.events = deque(maxlen=max_events)
        self.target_reached_size = target_reached_size
        self._last = {
            "mode": None,
            "target_visible": False,
            "target_size": None,
            "safety_reason": None,
            "control_link_ok": False,
        }
        self._approaching = False
        self._turning = None

    def _emit(self, event_type, **data):
        event = {
            "type": event_type,
            "monotonic": time.monotonic(),
            "timestamp": time.time(),
            "data": data,
        }
        self.events.append(event)
        print(f"[EVENT] {event_type}" + (f" {data}" if data else ""))
        return event

    def update(self, state):
        emitted = []

        mode = state.mode
        target_visible = state.observation.visual_target_visible
        target_x = state.observation.visual_target_x
        target_size = state.observation.visual_target_size
        throttle = state.intent.throttle
        steering = state.intent.steering
        safety_reason = state.safety.reason
        control_link_ok = state.safety.control_link_ok

        if self._last["mode"] is None:
            self._last["mode"] = mode
        elif mode != self._last["mode"]:
            emitted.append(self._emit(
                "MODE_CHANGED",
                previous=self._last["mode"],
                current=mode,
            ))
            if mode == "FOLLOW":
                emitted.append(self._emit("FOLLOW_STARTED"))
            elif self._last["mode"] == "FOLLOW":
                emitted.append(self._emit("FOLLOW_STOPPED"))

        if target_visible and not self._last["target_visible"]:
            emitted.append(self._emit(
                "TARGET_ACQUIRED",
                target_id=state.observation.visual_target_id,
                x=target_x,
                size=target_size,
            ))
        elif not target_visible and self._last["target_visible"]:
            emitted.append(self._emit("TARGET_LOST"))

        currently_approaching = (
            mode == "FOLLOW"
            and target_visible
            and throttle > 0.001
        )

        if currently_approaching and not self._approaching:
            emitted.append(self._emit(
                "APPROACH_STARTED",
                throttle=throttle,
                target_size=target_size,
            ))
        elif not currently_approaching and self._approaching:
            emitted.append(self._emit(
                "APPROACH_STOPPED",
                target_size=target_size,
            ))

        self._approaching = currently_approaching

        if (
            mode == "FOLLOW"
            and target_visible
            and abs(throttle) < 0.001
            and target_size is not None
            and target_size >= self.target_reached_size
        ):
            last_size = self._last["target_size"]
            if last_size is None or last_size < self.target_reached_size:
                emitted.append(self._emit(
                    "TARGET_REACHED",
                    target_size=target_size,
                ))

        turn_direction = None
        if steering < -0.05:
            turn_direction = "LEFT"
        elif steering > 0.05:
            turn_direction = "RIGHT"

        if turn_direction != self._turning:
            if self._turning is not None:
                emitted.append(self._emit(
                    "TURN_STOPPED",
                    previous=self._turning,
                ))
            if turn_direction is not None:
                emitted.append(self._emit(
                    f"TURN_{turn_direction}_STARTED",
                    steering=steering,
                ))
            self._turning = turn_direction

        if control_link_ok and not self._last["control_link_ok"]:
            emitted.append(self._emit("CONTROL_CONNECTED"))
        elif not control_link_ok and self._last["control_link_ok"]:
            emitted.append(self._emit("CONTROL_LOST"))

        if safety_reason != self._last["safety_reason"]:
            if safety_reason == "EMERGENCY STOP":
                emitted.append(self._emit("EMERGENCY_STOP"))
            elif safety_reason == "OBSTACLE":
                emitted.append(self._emit("OBSTACLE_STOP"))
            elif safety_reason == "CLEAR":
                emitted.append(self._emit("SAFETY_CLEAR"))

        self._last = {
            "mode": mode,
            "target_visible": target_visible,
            "target_size": target_size,
            "safety_reason": safety_reason,
            "control_link_ok": control_link_ok,
        }

        return emitted

    def recent(self, limit=20):
        return list(self.events)[-limit:]
