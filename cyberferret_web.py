import asyncio
import json
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, StreamingResponse

from cyberferret_camera import CyberFerretCamera
from cyberferret_drive import CyberFerretDrive
from cyberferret_events import EventDetector
from cyberferret_recorder import ExperienceRecorder
from cyberferret_state import FerretState
from cyberferret_vision import ArucoVision


CONTROL_HZ = 50
CONTROL_DT = 1.0 / CONTROL_HZ
CONTROL_TIMEOUT_S = 0.5

MAX_FORWARD = 0.30
MAX_REVERSE = 0.20
THROTTLE_RAMP_PER_SEC = 0.50
STEERING_RAMP_PER_SEC = 2.5

VISION_HZ = 8

FOLLOW_STEERING_GAIN = 0.75
FOLLOW_STEERING_DEADBAND = 0.10
FOLLOW_FILTER_ALPHA = 0.28
FOLLOW_ACQUIRE_FRAMES = 2

FOLLOW_TARGET_SIZE = 0.23
FOLLOW_SLOW_SIZE = 0.17

FOLLOW_MAX_THROTTLE = 0.07
FOLLOW_SLOW_THROTTLE = 0.03


drive = CyberFerretDrive()
state = FerretState()
state_lock = threading.Lock()

camera = CyberFerretCamera(
    size=(640, 480),
    jpeg_quality=70,
    capture_fps=15,
)

vision = ArucoVision(target_id=7)

events = EventDetector(
    max_events=100,
    target_reached_size=FOLLOW_TARGET_SIZE,
)

recorder = ExperienceRecorder(
    camera=camera,
    state=state,
    interval_s=0.25,
)


pressed_keys = set()
last_control_message = 0.0

desired_throttle = 0.0
desired_steering = 0.0

autonomy_enabled = False

control_task = None
vision_task = None
event_task = None

follow_filtered_x = None
follow_filtered_size = None
follow_visible_frames = 0


def approach(current, target, amount):
    if current < target:
        return min(current + amount, target)

    if current > target:
        return max(current - amount, target)

    return current


def low_pass(previous, value, alpha):
    if value is None:
        return previous

    if previous is None:
        return value

    return (
        previous * (1.0 - alpha)
        + value * alpha
    )


def reset_follow_filter():
    global follow_filtered_x
    global follow_filtered_size
    global follow_visible_frames

    follow_filtered_x = None
    follow_filtered_size = None
    follow_visible_frames = 0


def set_intent(throttle, steering, source):
    throttle = float(throttle)
    steering = float(steering)

    with state_lock:
        changed = (
            state.intent.source != source
            or abs(
                state.intent.throttle
                - throttle
            ) > 0.0001
            or abs(
                state.intent.steering
                - steering
            ) > 0.0001
        )

        if not changed:
            return

        state.intent.sequence += 1
        state.intent.throttle = throttle
        state.intent.steering = steering
        state.intent.source = source
        state.intent.received_at = time.monotonic()
        state.intent.received_at_epoch = time.time()


def update_safety():
    now = time.monotonic()
    control_age = now - last_control_message

    state.safety.control_link_ok = (
        control_age <= CONTROL_TIMEOUT_S
    )

    state.safety.watchdog_stop = (
        state.mode == "MANUAL"
        and not state.safety.control_link_ok
    )

    if state.safety.emergency_stop:
        state.safety.reason = "EMERGENCY STOP"

    elif state.safety.obstacle_stop:
        state.safety.reason = "OBSTACLE"

    elif state.safety.watchdog_stop:
        state.safety.reason = "CONTROL LINK LOST"

    else:
        state.safety.reason = "CLEAR"


async def vision_loop():
    interval = 1.0 / VISION_HZ

    last_sequence = -1

    vision_counter = 0
    vision_timer = time.monotonic()

    while True:
        started = time.monotonic()

        frame = camera.get_latest()

        if (
            frame is not None
            and frame["sequence"] != last_sequence
        ):
            last_sequence = frame["sequence"]

            result = await asyncio.to_thread(
                vision.detect_jpeg,
                frame["jpeg"],
            )

            with state_lock:
                state.observation.sequence = (
                    frame["sequence"]
                )

                state.observation.captured_at = (
                    frame["monotonic_timestamp"]
                )

                state.observation.captured_at_epoch = (
                    frame["timestamp"]
                )

                state.observation.width = (
                    frame["width"]
                )

                state.observation.height = (
                    frame["height"]
                )

                state.observation.visual_target_visible = (
                    result["visible"]
                )

                state.observation.visual_target_id = (
                    result["id"]
                )

                state.observation.visual_target_x = (
                    result["x"]
                )

                state.observation.visual_target_y = (
                    result["y"]
                )

                state.observation.visual_target_size = (
                    result["size"]
                )

            vision_counter += 1

            now = time.monotonic()
            elapsed = now - vision_timer

            if elapsed >= 1.0:
                with state_lock:
                    state.vision_hz = (
                        vision_counter
                        / elapsed
                    )

                vision_counter = 0
                vision_timer = now

        spent = time.monotonic() - started

        await asyncio.sleep(
            max(
                0.0,
                interval - spent,
            )
        )


async def event_loop():
    while True:
        with state_lock:
            emitted = events.update(state)

            if emitted:
                state.events.sequence += (
                    len(emitted)
                )

                state.events.last_type = (
                    emitted[-1]["type"]
                )

                state.events.last_timestamp = (
                    emitted[-1]["timestamp"]
                )

                state.events.recent = (
                    events.recent(20)
                )

        await asyncio.sleep(0.05)


async def control_loop():
    global desired_throttle
    global desired_steering
    global follow_filtered_x
    global follow_filtered_size
    global follow_visible_frames

    loop_counter = 0
    loop_timer = time.monotonic()

    while True:
        loop_started = time.monotonic()

        target_throttle = 0.0
        target_steering = 0.0

        state.safety.emergency_stop = (
            "space" in pressed_keys
        )

        if autonomy_enabled:
            state.mode = "FOLLOW"

            with state_lock:
                visible = (
                    state.observation
                    .visual_target_visible
                )

                target_x = (
                    state.observation
                    .visual_target_x
                )

                target_size = (
                    state.observation
                    .visual_target_size
                )

            if (
                not visible
                or target_x is None
                or target_size is None
            ):
                target_throttle = 0.0
                target_steering = 0.0
                reset_follow_filter()

            else:
                follow_visible_frames += 1

                follow_filtered_x = low_pass(
                    follow_filtered_x,
                    target_x,
                    FOLLOW_FILTER_ALPHA,
                )

                follow_filtered_size = low_pass(
                    follow_filtered_size,
                    target_size,
                    FOLLOW_FILTER_ALPHA,
                )

                acquired = (
                    follow_visible_frames
                    >= FOLLOW_ACQUIRE_FRAMES
                )

                if (
                    acquired
                    and follow_filtered_x is not None
                    and abs(follow_filtered_x)
                    > FOLLOW_STEERING_DEADBAND
                ):
                    target_steering = max(
                        -1.0,
                        min(
                            1.0,
                            follow_filtered_x
                            * FOLLOW_STEERING_GAIN,
                        ),
                    )

                if (
                    acquired
                    and follow_filtered_size is not None
                ):
                    if (
                        follow_filtered_size
                        >= FOLLOW_TARGET_SIZE
                    ):
                        target_throttle = 0.0

                    elif (
                        follow_filtered_size
                        >= FOLLOW_SLOW_SIZE
                    ):
                        target_throttle = (
                            FOLLOW_SLOW_THROTTLE
                        )

                    else:
                        target_throttle = (
                            FOLLOW_MAX_THROTTLE
                        )

            # FOLLOW cannot reverse.
            target_throttle = max(
                0.0,
                target_throttle,
            )

            set_intent(
                target_throttle,
                target_steering,
                "vision-follow",
            )

        else:
            state.mode = "MANUAL"

            if (
                "w" in pressed_keys
                and "s" not in pressed_keys
            ):
                target_throttle = MAX_FORWARD

            elif (
                "s" in pressed_keys
                and "w" not in pressed_keys
            ):
                target_throttle = -MAX_REVERSE

            if (
                "a" in pressed_keys
                and "d" not in pressed_keys
            ):
                target_steering = -1.0

            elif (
                "d" in pressed_keys
                and "a" not in pressed_keys
            ):
                target_steering = 1.0

            set_intent(
                target_throttle,
                target_steering,
                "browser",
            )

        update_safety()

        if not state.safety.clear:
            target_throttle = 0.0

        if state.safety.emergency_stop:
            desired_throttle = 0.0

        else:
            desired_throttle = approach(
                desired_throttle,
                target_throttle,
                THROTTLE_RAMP_PER_SEC
                * CONTROL_DT,
            )

        desired_steering = approach(
            desired_steering,
            target_steering,
            STEERING_RAMP_PER_SEC
            * CONTROL_DT,
        )

        drive.throttle(
            desired_throttle
        )

        drive.steer(
            desired_steering
        )

        hardware_status = (
            drive.status()
        )

        body_now = time.monotonic()
        body_epoch = time.time()

        with state_lock:
            state.body.sequence += 1

            state.body.commanded_throttle = (
                desired_throttle
            )

            state.body.commanded_steering = (
                desired_steering
            )

            state.body.throttle_us = (
                hardware_status[
                    "throttle_us"
                ]
            )

            state.body.steering_deg = (
                hardware_status[
                    "steering_deg"
                ]
            )

            state.body.updated_at = (
                body_now
            )

            state.body.updated_at_epoch = (
                body_epoch
            )

            state.camera_fps = (
                camera.fps
            )

        loop_counter += 1

        now = time.monotonic()
        elapsed = now - loop_timer

        if elapsed >= 1.0:
            with state_lock:
                state.loop_hz = (
                    loop_counter
                    / elapsed
                )

            loop_counter = 0
            loop_timer = now

        spent = (
            time.monotonic()
            - loop_started
        )

        await asyncio.sleep(
            max(
                0.0,
                CONTROL_DT - spent,
            )
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    global control_task
    global vision_task
    global event_task
    global pressed_keys

    print("Cyber Ferret waking up...")

    camera.start()
    recorder.start()

    vision_task = asyncio.create_task(
        vision_loop()
    )

    control_task = asyncio.create_task(
        control_loop()
    )

    event_task = asyncio.create_task(
        event_loop()
    )

    try:
        yield

    finally:
        print(
            "Cyber Ferret shutting down..."
        )

        pressed_keys = set()
        state.safety.emergency_stop = True

        drive.stop()

        for task in (
            control_task,
            vision_task,
            event_task,
        ):
            if task:
                task.cancel()

        for task in (
            control_task,
            vision_task,
            event_task,
        ):
            if task:
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        drive.stop()

        recorder.stop()
        camera.stop()
        drive.shutdown()

        print("Cyber Ferret asleep.")


app = FastAPI(
    lifespan=lifespan
)


async def mjpeg_generator():
    last_sequence = -1

    try:
        while True:
            frame = camera.get_latest()

            if frame is None:
                await asyncio.sleep(0.02)
                continue

            if (
                frame["sequence"]
                == last_sequence
            ):
                await asyncio.sleep(0.01)
                continue

            last_sequence = (
                frame["sequence"]
            )

            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n"
                + frame["jpeg"]
                + b"\r\n"
            )

            await asyncio.sleep(0)

    except asyncio.CancelledError:
        print(
            "Camera stream disconnected"
        )
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


@app.websocket("/ws")
async def websocket_endpoint(
    ws: WebSocket
):
    global pressed_keys
    global last_control_message
    global autonomy_enabled
    global desired_throttle
    global desired_steering

    await ws.accept()

    pressed_keys = set()

    last_control_message = (
        time.monotonic()
    )

    try:
        while True:
            raw = await ws.receive_text()

            msg = json.loads(raw)
            message_type = msg.get("type")

            if message_type == "control":
                pressed_keys = set(
                    msg.get(
                        "keys",
                        [],
                    )
                )

                last_control_message = (
                    time.monotonic()
                )

            elif message_type == "mode":
                requested_mode = (
                    msg.get("mode")
                )

                if requested_mode == "FOLLOW":
                    pressed_keys = set()

                    desired_throttle = 0.0
                    desired_steering = 0.0

                    drive.stop()
                    drive.center()

                    reset_follow_filter()

                    autonomy_enabled = True

                    set_intent(
                        0.0,
                        0.0,
                        "vision-follow",
                    )

                elif requested_mode == "MANUAL":
                    autonomy_enabled = False

                    pressed_keys = set()

                    desired_throttle = 0.0
                    desired_steering = 0.0

                    drive.stop()
                    drive.center()

                    reset_follow_filter()

                    last_control_message = (
                        time.monotonic()
                    )

                    set_intent(
                        0.0,
                        0.0,
                        "browser",
                    )

            with state_lock:
                payload = (
                    state.to_dict()
                )

            await ws.send_text(
                json.dumps(payload)
            )

    except WebSocketDisconnect:
        pressed_keys = set()


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
SPACE remains emergency stop in either mode.
</div>

<script>
let ws = null

const keys = new Set()

const manualButton =
    document.getElementById(
        "manualButton"
    )

const followButton =
    document.getElementById(
        "followButton"
    )


function displayValue(
    id,
    value,
    fallback = "---"
) {
    const element =
        document.getElementById(
            id
        )

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

        setTimeout(
            connect,
            1000
        )
    }

    ws.onmessage = event => {
        const s = JSON.parse(
            event.data
        )

        displayValue(
            "mode",
            s.mode
        )

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
            document.getElementById(
                "cameraLabel"
            )

        if (
            s.observation
                .visual_target_visible
        ) {
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
            document.getElementById(
                "controlLink"
            )

        control.textContent =
            s.safety.control_link_ok
                ? "ONLINE"
                : (
                    s.mode === "FOLLOW"
                        ? "NOT REQUIRED"
                        : "LOST"
                )

        control.className =
            (
                s.safety.control_link_ok
                || s.mode === "FOLLOW"
            )
                ? "good"
                : "bad"

        const safety =
            document.getElementById(
                "safety"
            )

        safety.textContent =
            s.safety.reason

        safety.className =
            s.safety.clear
                ? "good"
                : "bad"
    }
}


connect()


function sendState() {
    if (
        !ws
        || ws.readyState
            !== WebSocket.OPEN
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


setInterval(
    sendState,
    50
)


function setMode(mode) {
    if (
        !ws
        || ws.readyState
            !== WebSocket.OPEN
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


function keyName(event) {
    if (
        event.code === "Space"
    ) {
        return "space"
    }

    return event.key
        .toLowerCase()
}


function setKeyUI(
    key,
    active
) {
    const element =
        document.getElementById(
            `key-${key}`
        )

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
        of [
            "w",
            "a",
            "s",
            "d",
            "space",
        ]
    ) {
        setKeyUI(
            key,
            false
        )
    }
}


window.addEventListener(
    "keydown",
    event => {
        const key =
            keyName(event)

        if (
            ![
                "w",
                "a",
                "s",
                "d",
                "space",
            ].includes(key)
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
        setKeyUI(
            key,
            true
        )

        sendState()
    }
)


window.addEventListener(
    "keyup",
    event => {
        const key =
            keyName(event)

        keys.delete(key)
        setKeyUI(
            key,
            false
        )

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
    return HTMLResponse(
        HTML
    )
