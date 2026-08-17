import asyncio
import json
import os
import threading
import time
import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, StreamingResponse

import cyberferret_safety as safety
from cyberferret_control import approach
from cyberferret_events import EventDetector
from cyberferret_follow import FollowController
from cyberferret_recorder import ExperienceRecorder
from cyberferret_state import FerretState
from cyberferret_vision import ArucoVision


CONTROL_HZ = 50
CONTROL_DT = 1.0 / CONTROL_HZ

MAX_FORWARD = 0.30
MAX_REVERSE = 0.20
THROTTLE_RAMP_PER_SEC = 0.50
STEERING_RAMP_PER_SEC = 2.5

VISION_HZ = 8
EVENT_HZ = 20


SIM_MODE = os.environ.get("CYBERFERRET_SIM") == "1"

if SIM_MODE:
    import cyberferret_sim

    print("CYBERFERRET_SIM=1: running against the simulated body")
    drive, camera = cyberferret_sim.build()

else:
    from cyberferret_camera import CyberFerretCamera
    from cyberferret_drive import CyberFerretDrive

    drive = CyberFerretDrive()
    camera = CyberFerretCamera(
        size=(640, 480),
        jpeg_quality=70,
        capture_fps=15,
    )


state = FerretState()
state_lock = threading.Lock()

vision = ArucoVision(target_id=7)
follow = FollowController()

events = EventDetector(
    max_events=100,
    target_reached_size=follow.target_size,
)

recorder = ExperienceRecorder(
    camera=camera,
    state=state,
    interval_s=0.25,
)


class ControlHub:
    """Shared inputs between the websocket handler and the control thread.

    Everything a browser can influence lives here, behind one lock, so the
    control thread reads a coherent snapshot each cycle.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.pressed_keys = set()
        self.last_control_message = None
        self.autonomy_enabled = False
        self.autonomy_armed_at = None
        self.estop_latched = False
        self.controller_connected = False

    def snapshot(self, now):
        with self.lock:
            if "space" in self.pressed_keys:
                self.estop_latched = True

            if self.last_control_message is None:
                link_age = float("inf")
            else:
                link_age = now - self.last_control_message

            if self.autonomy_armed_at is None:
                autonomy_age = None
            else:
                autonomy_age = now - self.autonomy_armed_at

            return {
                "keys": set(self.pressed_keys),
                "link_age": link_age,
                "autonomy": self.autonomy_enabled,
                "autonomy_age": autonomy_age,
                "estop": self.estop_latched,
            }

    def disarm_autonomy(self):
        with self.lock:
            self.autonomy_enabled = False
            self.autonomy_armed_at = None


hub = ControlHub()

_stop_threads = threading.Event()


def compute_manual_targets(keys):
    throttle = 0.0
    steering = 0.0

    if "w" in keys and "s" not in keys:
        throttle = MAX_FORWARD
    elif "s" in keys and "w" not in keys:
        throttle = -MAX_REVERSE

    if "a" in keys and "d" not in keys:
        steering = -1.0
    elif "d" in keys and "a" not in keys:
        steering = 1.0

    return throttle, steering


def set_intent(throttle, steering, source):
    throttle = float(throttle)
    steering = float(steering)

    with state_lock:
        changed = (
            state.intent.source != source
            or abs(state.intent.throttle - throttle) > 0.0001
            or abs(state.intent.steering - steering) > 0.0001
        )

        if not changed:
            return

        state.intent.sequence += 1
        state.intent.throttle = throttle
        state.intent.steering = steering
        state.intent.source = source
        state.intent.received_at = time.monotonic()
        state.intent.received_at_epoch = time.time()


def control_cycle(desired_throttle, desired_steering):
    """One 50 Hz iteration. Returns the new ramped commands."""

    now = time.monotonic()
    inputs = hub.snapshot(now)

    mode = "FOLLOW" if inputs["autonomy"] else "MANUAL"

    if mode == "FOLLOW":
        with state_lock:
            visible = state.observation.visual_target_visible
            target_x = state.observation.visual_target_x
            target_size = state.observation.visual_target_size

        proposal = follow.update(visible, target_x, target_size)
        target_throttle = proposal.throttle
        target_steering = proposal.steering

        with state_lock:
            state.behavior.follow_acquired = proposal.acquired
            state.behavior.follow_filtered_x = proposal.filtered_x
            state.behavior.follow_filtered_size = proposal.filtered_size

        set_intent(target_throttle, target_steering, "vision-follow")

    else:
        target_throttle, target_steering = (
            compute_manual_targets(inputs["keys"])
        )

        with state_lock:
            state.behavior.follow_acquired = False
            state.behavior.follow_filtered_x = None
            state.behavior.follow_filtered_size = None

        set_intent(target_throttle, target_steering, "browser")

    decision = safety.arbitrate(
        safety.SafetyInputs(
            mode=mode,
            emergency_stop_latched=inputs["estop"],
            control_link_age_s=inputs["link_age"],
            autonomy_age_s=inputs["autonomy_age"],
            obstacle_stop=False,
        )
    )

    if mode == "FOLLOW" and decision.disarm_autonomy:
        # Autonomy never resumes on its own. A human re-arms it.
        hub.disarm_autonomy()
        follow.reset()
        mode = "MANUAL"

    if not decision.clear:
        target_throttle = 0.0

    if decision.emergency_stop:
        desired_throttle = 0.0
        target_throttle = 0.0
    else:
        desired_throttle = approach(
            desired_throttle,
            target_throttle,
            THROTTLE_RAMP_PER_SEC * CONTROL_DT,
        )

    desired_steering = approach(
        desired_steering,
        target_steering,
        STEERING_RAMP_PER_SEC * CONTROL_DT,
    )

    drive.throttle(desired_throttle)
    drive.steer(desired_steering)

    hardware_status = drive.status()

    with state_lock:
        state.mode = mode

        state.safety.control_link_ok = decision.control_link_ok
        state.safety.emergency_stop = decision.emergency_stop
        state.safety.obstacle_stop = decision.obstacle_stop
        state.safety.link_stop = decision.link_stop
        state.safety.autonomy_expired = decision.autonomy_expired
        state.safety.reason = decision.reason
        state.safety.autonomy_age_s = inputs["autonomy_age"]
        state.safety.autonomy_limit_s = safety.AUTONOMY_MAX_DURATION_S

        state.body.sequence += 1
        state.body.commanded_throttle = desired_throttle
        state.body.commanded_steering = desired_steering
        state.body.throttle_us = hardware_status["throttle_us"]
        state.body.steering_deg = hardware_status["steering_deg"]
        state.body.updated_at = now
        state.body.updated_at_epoch = time.time()

        state.camera_fps = camera.fps

    return desired_throttle, desired_steering


def control_thread_main():
    """The 50 Hz loop, in its own thread.

    Deliberately not a coroutine: it must not share a scheduler with HTTP
    handlers and video streaming. If this thread dies, the drive layer's
    independent hardware watchdog returns propulsion to neutral.
    """

    desired_throttle = 0.0
    desired_steering = 0.0

    loop_counter = 0
    loop_timer = time.monotonic()

    try:
        while not _stop_threads.is_set():
            started = time.monotonic()

            desired_throttle, desired_steering = control_cycle(
                desired_throttle,
                desired_steering,
            )

            loop_counter += 1
            elapsed = started - loop_timer

            if elapsed >= 1.0:
                with state_lock:
                    state.loop_hz = loop_counter / elapsed
                loop_counter = 0
                loop_timer = started

            spent = time.monotonic() - started
            time.sleep(max(0.0, CONTROL_DT - spent))

    except Exception:
        print("[CONTROL] loop crashed:")
        traceback.print_exc()

        with state_lock:
            state.safety.reason = "CONTROL FAULT"
            state.safety.link_stop = True

    finally:
        drive.stop()
        drive.center()


def vision_thread_main():
    interval = 1.0 / VISION_HZ
    last_sequence = -1

    vision_counter = 0
    vision_timer = time.monotonic()

    while not _stop_threads.is_set():
        started = time.monotonic()

        frame = camera.get_latest()

        if frame is not None and frame["sequence"] != last_sequence:
            last_sequence = frame["sequence"]

            try:
                result = vision.detect_jpeg(frame["jpeg"])
            except Exception:
                print("[VISION] detection failed:")
                traceback.print_exc()
                result = None

            if result is not None:
                with state_lock:
                    state.observation.sequence = frame["sequence"]
                    state.observation.captured_at = (
                        frame["monotonic_timestamp"]
                    )
                    state.observation.captured_at_epoch = (
                        frame["timestamp"]
                    )
                    state.observation.width = frame["width"]
                    state.observation.height = frame["height"]
                    state.observation.visual_target_visible = (
                        result["visible"]
                    )
                    state.observation.visual_target_id = result["id"]
                    state.observation.visual_target_x = result["x"]
                    state.observation.visual_target_y = result["y"]
                    state.observation.visual_target_size = (
                        result["size"]
                    )

                vision_counter += 1

            now = time.monotonic()
            elapsed = now - vision_timer

            if elapsed >= 1.0:
                with state_lock:
                    state.vision_hz = vision_counter / elapsed
                vision_counter = 0
                vision_timer = now

        spent = time.monotonic() - started
        time.sleep(max(0.0, interval - spent))


def event_thread_main():
    interval = 1.0 / EVENT_HZ

    while not _stop_threads.is_set():
        with state_lock:
            emitted = events.update(state)

            if emitted:
                state.events.sequence += len(emitted)
                state.events.last_type = emitted[-1]["type"]
                state.events.last_timestamp = emitted[-1]["timestamp"]
                state.events.recent = events.recent(20)

        time.sleep(interval)


_threads = []


def start_threads():
    _stop_threads.clear()

    for name, target in (
        ("control", control_thread_main),
        ("vision", vision_thread_main),
        ("events", event_thread_main),
    ):
        thread = threading.Thread(
            target=target,
            name=name,
            daemon=True,
        )
        thread.start()
        _threads.append(thread)


def stop_threads():
    _stop_threads.set()

    for thread in _threads:
        thread.join(timeout=2)

    _threads.clear()


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Cyber Ferret waking up...")

    camera.start()
    recorder.start()
    start_threads()

    try:
        yield

    finally:
        print("Cyber Ferret shutting down...")

        with hub.lock:
            hub.pressed_keys = set()
            hub.estop_latched = True

        stop_threads()

        drive.stop()
        recorder.stop()
        camera.stop()
        drive.shutdown()

        print("Cyber Ferret asleep.")


app = FastAPI(lifespan=lifespan)


async def mjpeg_generator():
    last_sequence = -1

    try:
        while True:
            frame = camera.get_latest()

            if frame is None:
                await asyncio.sleep(0.02)
                continue

            if frame["sequence"] == last_sequence:
                await asyncio.sleep(0.01)
                continue

            last_sequence = frame["sequence"]

            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n"
                + frame["jpeg"]
                + b"\r\n"
            )

            await asyncio.sleep(0)

    except asyncio.CancelledError:
        print("Camera stream disconnected")
        raise


@app.get("/camera")
async def camera_stream():
    return StreamingResponse(
        mjpeg_generator(),
        media_type=(
            "multipart/x-mixed-replace;"
            " boundary=frame"
        ),
        headers={
            "Cache-Control": (
                "no-store, no-cache, "
                "must-revalidate, max-age=0"
            )
        },
    )


def handle_control_message(msg):
    with hub.lock:
        hub.pressed_keys = set(msg.get("keys", []))
        hub.last_control_message = time.monotonic()


def handle_mode_message(msg):
    requested = msg.get("mode")

    if requested == "FOLLOW":
        with hub.lock:
            if hub.estop_latched:
                # Arming autonomy while the e-stop is latched would let a
                # single keypress launch the vehicle. Clear it first.
                return

            hub.pressed_keys = set()
            hub.autonomy_enabled = True
            hub.autonomy_armed_at = time.monotonic()
            hub.last_control_message = time.monotonic()

        follow.reset()
        set_intent(0.0, 0.0, "vision-follow")

    elif requested == "MANUAL":
        hub.disarm_autonomy()

        with hub.lock:
            hub.pressed_keys = set()
            hub.last_control_message = time.monotonic()

        follow.reset()
        set_intent(0.0, 0.0, "browser")


def handle_estop_clear():
    with hub.lock:
        if "space" in hub.pressed_keys:
            return

        hub.estop_latched = False
        hub.last_control_message = time.monotonic()


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()

    with hub.lock:
        if hub.controller_connected:
            already_controlled = True
        else:
            hub.controller_connected = True
            hub.pressed_keys = set()
            hub.last_control_message = time.monotonic()
            already_controlled = False

    if already_controlled:
        # One controller at a time. Two browsers fighting over pressed_keys
        # is how a rover ends up under the couch.
        await ws.send_text(json.dumps({
            "error": "another controller is already connected",
        }))
        await ws.close(code=1008)
        return

    try:
        while True:
            raw = await ws.receive_text()

            msg = json.loads(raw)
            message_type = msg.get("type")

            if message_type == "control":
                handle_control_message(msg)

            elif message_type == "mode":
                handle_mode_message(msg)

            elif message_type == "estop_clear":
                handle_estop_clear()

            with state_lock:
                payload = state.to_dict()

            await ws.send_text(json.dumps(payload))

    except WebSocketDisconnect:
        pass

    finally:
        with hub.lock:
            hub.controller_connected = False
            hub.pressed_keys = set()


HTML = r"""
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Cyber Ferret</title>

<style>
* { box-sizing: border-box; }

body {
    margin: 0;
    padding: 20px;
    background: #0d0f10;
    color: #e6e6e6;
    font-family:
        ui-monospace,
        SFMono-Regular,
        Menlo,
        Monaco,
        Consolas,
        monospace;
}

header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 16px;
    max-width: 1000px;
    margin: auto;
}

h1 {
    margin: 0;
    font-size: 22px;
    letter-spacing: 1px;
}

.mode-buttons {
    display: flex;
    gap: 8px;
}

button {
    font: inherit;
    padding: 8px 12px;
    color: #eee;
    background: #181b1d;
    border: 1px solid #444;
    border-radius: 8px;
    cursor: pointer;
}

button.active {
    border-color: #7dff9b;
    color: #7dff9b;
}

button.danger {
    border-color: #ff6464;
    color: #ff6464;
}

button.hidden {
    display: none;
}

.camera {
    position: relative;
    max-width: 800px;
    margin: 15px auto;
    background: #000;
    border-radius: 14px;
    overflow: hidden;
}

.camera img {
    width: 100%;
    display: block;
}

.camera-label {
    position: absolute;
    top: 10px;
    left: 10px;
    padding: 5px 8px;
    background: rgba(0, 0, 0, 0.65);
    border-radius: 5px;
    font-size: 12px;
}

.panel {
    max-width: 1000px;
    margin: 15px auto;
    background: #181b1d;
    border: 1px solid #292d30;
    border-radius: 12px;
    padding: 16px;
}

.grid {
    display: grid;
    grid-template-columns:
        repeat(
            auto-fit,
            minmax(190px, 1fr)
        );
    gap: 14px;
}

.group {
    padding: 12px;
    background: #111315;
    border-radius: 8px;
}

.group-title {
    font-size: 12px;
    opacity: .55;
    margin-bottom: 8px;
}

.value {
    font-size: 16px;
    line-height: 1.7;
}

.good { color: #7dff9b; }
.bad { color: #ff6464; }
.target { color: #7ddcff; }
.waiting { opacity: .45; }

.keys {
    display: grid;
    grid-template-columns:
        repeat(3, 80px);
    gap: 8px;
    justify-content: center;
    margin: 20px;
}

.key {
    height: 65px;
    border: 1px solid #444;
    border-radius: 10px;
    display: flex;
    justify-content: center;
    align-items: center;
    font-size: 24px;
    background: #181b1d;
}

.key.active {
    background: #454b50;
}

.space {
    grid-column: 1 / 4;
}

.hint {
    max-width: 800px;
    margin: 8px auto;
    text-align: center;
    font-size: 12px;
    opacity: .55;
}
</style>
</head>

<body>

<header>
<h1>CYBER FERRET</h1>

<div class="mode-buttons">
<button id="estopClearButton" class="danger hidden">
CLEAR E-STOP
</button>

<button id="manualButton" class="active">
MANUAL
</button>

<button id="followButton">
FOLLOW MARKER
</button>
</div>
</header>

<div class="camera">
<img
    src="/camera"
    alt="Cyber Ferret Vision"
>

<div
    id="cameraLabel"
    class="camera-label"
>
FERRET VISION
</div>
</div>

<div class="panel">
<div class="grid">

<div class="group">
<div class="group-title">INTENT</div>
<div class="value">
Source: <span id="intentSource">---</span><br>
Throttle: <span id="intentThrottle">0</span><br>
Steering: <span id="intentSteering">0</span><br>
Sequence: <span id="intentSequence">0</span>
</div>
</div>

<div class="group">
<div class="group-title">BODY</div>
<div class="value">
Throttle: <span id="bodyThrottle">0</span><br>
PWM: <span id="throttleUs">---</span><br>
Steering: <span id="steeringDeg">---</span>°<br>
Sequence: <span id="bodySequence">0</span>
</div>
</div>

<div class="group">
<div class="group-title">VISION</div>
<div class="value">
Target: <span id="targetVisible">NO</span><br>
ID: <span id="targetId">---</span><br>
X: <span id="targetX">---</span><br>
Size: <span id="targetSize">---</span><br>
Frame: <span id="observationSequence">---</span>
</div>
</div>

<div class="group">
<div class="group-title">EVENTS</div>
<div class="value">
Last: <span id="lastEvent">---</span><br>
Count: <span id="eventCount">0</span>
</div>
</div>

<div class="group">
<div class="group-title">WORLD</div>
<div class="value waiting">
Front: <span id="front">---</span><br>
Left: <span id="left">---</span><br>
Right: <span id="right">---</span><br>
Ground speed: <span id="groundSpeed">---</span>
</div>
</div>

<div class="group">
<div class="group-title">SYSTEM</div>
<div class="value">
Mode: <span id="mode">MANUAL</span><br>
Control: <span id="controlLink">---</span><br>
Safety: <span id="safety">---</span><br>
Autonomy: <span id="autonomyBudget">---</span><br>
Loop: <span id="loopHz">---</span> Hz<br>
Camera: <span id="cameraFps">---</span> fps<br>
Vision: <span id="visionHz">---</span> Hz
</div>
</div>

</div>
</div>

<div class="keys">
<div></div>
<div id="key-w" class="key">W</div>
<div></div>

<div id="key-a" class="key">A</div>
<div id="key-s" class="key">S</div>
<div id="key-d" class="key">D</div>

<div id="key-space" class="key space">
STOP
</div>
</div>

<div class="hint">
SPACE latches the emergency stop in either mode.
Clear it with the CLEAR E-STOP button.
</div>

<script>
let ws = null
let reconnectDelay = 1000

const keys = new Set()

const manualButton =
    document.getElementById("manualButton")

const followButton =
    document.getElementById("followButton")

const estopClearButton =
    document.getElementById("estopClearButton")


function displayValue(
    id,
    value,
    fallback = "---"
) {
    const element =
        document.getElementById(id)

    if (!element) {
        return
    }

    element.textContent =
        value === null
        || value === undefined
            ? fallback
            : value
}


function connect() {
    const protocol =
        location.protocol === "https:"
            ? "wss"
            : "ws"

    ws = new WebSocket(
        `${protocol}://${location.host}/ws`
    )

    ws.onclose = () => {
        keys.clear()
        clearKeyUI()

        setTimeout(connect, reconnectDelay)
    }

    ws.onmessage = event => {
        const s = JSON.parse(event.data)

        if (s.error) {
            // Another tab owns control. Keep watching the camera and
            // retry slowly in case that controller goes away.
            document.title = "Cyber Ferret (view only)"
            displayValue("safety", s.error)
            reconnectDelay = 5000
            return
        }

        document.title = "Cyber Ferret"
        reconnectDelay = 1000

        displayValue("mode", s.mode)

        displayValue(
            "intentSource",
            s.intent.source
        )

        displayValue(
            "intentThrottle",
            s.intent.throttle.toFixed(2)
        )

        displayValue(
            "intentSteering",
            s.intent.steering.toFixed(2)
        )

        displayValue(
            "intentSequence",
            s.intent.sequence
        )

        displayValue(
            "bodyThrottle",
            s.body.commanded_throttle.toFixed(2)
        )

        displayValue(
            "throttleUs",
            s.body.throttle_us
        )

        displayValue(
            "steeringDeg",
            s.body.steering_deg.toFixed(1)
        )

        displayValue(
            "bodySequence",
            s.body.sequence
        )

        displayValue(
            "observationSequence",
            s.observation.sequence
        )

        displayValue(
            "targetVisible",
            s.observation.visual_target_visible
                ? "YES"
                : "NO"
        )

        displayValue(
            "targetId",
            s.observation.visual_target_id
        )

        displayValue(
            "targetX",
            s.observation.visual_target_x === null
                ? "---"
                : s.observation.visual_target_x.toFixed(2)
        )

        displayValue(
            "targetSize",
            s.observation.visual_target_size === null
                ? "---"
                : s.observation.visual_target_size.toFixed(3)
        )

        displayValue(
            "lastEvent",
            s.events.last_type
        )

        displayValue(
            "eventCount",
            s.events.sequence
        )

        displayValue(
            "loopHz",
            s.loop_hz.toFixed(1)
        )

        displayValue(
            "cameraFps",
            s.camera_fps.toFixed(1)
        )

        displayValue(
            "visionHz",
            s.vision_hz.toFixed(1)
        )

        if (
            s.mode === "FOLLOW"
            && s.safety.autonomy_age_s !== null
            && s.safety.autonomy_limit_s !== null
        ) {
            const remaining =
                s.safety.autonomy_limit_s
                - s.safety.autonomy_age_s

            displayValue(
                "autonomyBudget",
                `${Math.max(0, remaining).toFixed(0)}s left`
            )
        } else {
            displayValue("autonomyBudget", "---")
        }

        estopClearButton
            .classList
            .toggle(
                "hidden",
                !s.safety.emergency_stop
            )

        manualButton
            .classList
            .toggle(
                "active",
                s.mode === "MANUAL"
            )

        followButton
            .classList
            .toggle(
                "active",
                s.mode === "FOLLOW"
            )

        const cameraLabel =
            document.getElementById("cameraLabel")

        if (s.observation.visual_target_visible) {
            cameraLabel.textContent =
                "TARGET ACQUIRED"

            cameraLabel.className =
                "camera-label target"

        } else {
            cameraLabel.textContent =
                "FERRET VISION"

            cameraLabel.className =
                "camera-label"
        }

        const control =
            document.getElementById("controlLink")

        control.textContent =
            s.safety.control_link_ok
                ? "ONLINE"
                : "LOST"

        control.className =
            s.safety.control_link_ok
                ? "good"
                : "bad"

        const safetyElement =
            document.getElementById("safety")

        safetyElement.textContent =
            s.safety.reason

        safetyElement.className =
            s.safety.clear
                ? "good"
                : "bad"
    }
}


connect()


function sendState() {
    if (
        !ws
        || ws.readyState !== WebSocket.OPEN
    ) {
        return
    }

    ws.send(
        JSON.stringify({
            type: "control",
            keys: [...keys]
        })
    )
}


setInterval(sendState, 50)


function setMode(mode) {
    if (
        !ws
        || ws.readyState !== WebSocket.OPEN
    ) {
        return
    }

    keys.clear()
    clearKeyUI()

    ws.send(
        JSON.stringify({
            type: "mode",
            mode
        })
    )
}


manualButton.onclick = () => {
    setMode("MANUAL")
}


followButton.onclick = () => {
    setMode("FOLLOW")
}


estopClearButton.onclick = () => {
    if (
        !ws
        || ws.readyState !== WebSocket.OPEN
    ) {
        return
    }

    ws.send(
        JSON.stringify({
            type: "estop_clear"
        })
    )
}


function keyName(event) {
    if (event.code === "Space") {
        return "space"
    }

    return event.key.toLowerCase()
}


function setKeyUI(key, active) {
    const element =
        document.getElementById(`key-${key}`)

    if (element) {
        element.classList.toggle(
            "active",
            active
        )
    }
}


function clearKeyUI() {
    for (
        const key
        of ["w", "a", "s", "d", "space"]
    ) {
        setKeyUI(key, false)
    }
}


window.addEventListener(
    "keydown",
    event => {
        const key = keyName(event)

        if (
            !["w", "a", "s", "d", "space"]
                .includes(key)
        ) {
            return
        }

        event.preventDefault()

        if (
            followButton
                .classList
                .contains("active")
            && key !== "space"
        ) {
            return
        }

        keys.add(key)
        setKeyUI(key, true)

        sendState()
    }
)


window.addEventListener(
    "keyup",
    event => {
        const key = keyName(event)

        keys.delete(key)
        setKeyUI(key, false)

        sendState()
    }
)


window.addEventListener(
    "blur",
    () => {
        keys.clear()
        clearKeyUI()
        sendState()
    }
)
</script>

</body>
</html>
"""


@app.get("/")
async def index():
    return HTMLResponse(HTML)
