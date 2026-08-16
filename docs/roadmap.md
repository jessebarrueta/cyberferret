# Cyber Ferret Roadmap

This is a living roadmap rather than a strict implementation sequence.

The general progression is:

**reliable body → richer senses → spatial reflexes → autonomous behavior → prediction → memory → higher-level cognition**

## Now — Stable embodied foundation

Working today:

- calibrated steering and ESC
- smooth throttle and steering
- return to center
- emergency stop and hardware watchdog
- browser HUD and manual driving
- Raspberry Pi camera and MJPEG stream
- ArUco marker detection
- autonomous FOLLOW mode
- target-loss stop
- conservative autonomous speed limits
- synchronized session recording
- semantic event detection

FOLLOW is now good enough to build upon. Richer physical sensing is more valuable than endlessly polishing marker following.

## Next — Sense physical space

### Range sensing

Integrate the incoming ToF sensors into observation state:

- front distance
- left distance
- right distance
- rear distance where useful
- downward / ground distance where useful

### Obstacle reflex

Build the first true sensor-fusion behavior:

```text
vision says GO
+
front range says TOO CLOSE
=
STOP
```

It should be deterministic, independent of FOLLOW, represented in safety state, emit `OBSTACLE_STOP`, and be recorded with surrounding observations.

### Spatial HUD

Expose live range measurements and safety decisions. Eventually add a small top-down proximity display.

### Steering-position feedback

Distinguish desired steering, commanded steering, and actual steering.

Use it for better centering, obstruction detection, linkage characterization, and command-vs-outcome comparison.

### Motion / orientation

Integrate heading, pitch, roll, yaw rate, and acceleration from the IMU.

### Ground or wheel speed

Add actual motion feedback. Comparing throttle command to measured movement enables prediction and stuck detection.

## Then — Autonomous movement without a marker

### Collision-resistant roaming

Start with deterministic local behavior:

- move forward slowly
- stop before obstacles
- compare open space left vs right
- turn toward safer space
- continue

### FERRET mode

Create an autonomous exploration mode separate from FOLLOW.

Initial objective:

> Explore novel reachable space while remaining safe.

### Stuck detection

Detect:

- throttle commanded but no movement
- steering commanded but steering position unchanged
- repeated obstacle loops
- repeated forward/turn oscillation

Emit semantic events rather than merely accumulating telemetry.

## Prediction and outcome

Begin recording predictions once outcomes can actually be measured.

```text
prediction:
turn right for 0.8 seconds
→ heading changes ~25 degrees

outcome:
heading changed 13 degrees

error:
-12 degrees
```

Or:

```text
prediction:
forward throttle should produce movement

outcome:
speed remained zero

hypothesis:
blocked or stuck
```

Prediction error tells the system when its model of itself or the world needs revision.

## Memory

### Episodes

Convert meaningful event sequences into episodes, for example:

```text
TARGET_ACQUIRED
FOLLOW_STARTED
OBSTACLE_STOP
TURNED_LEFT
TARGET_REACQUIRED
TARGET_REACHED
```

That is more useful to later reasoning than thousands of nearly identical telemetry records.

### Expiration and consolidation

Use different retention classes.

**Raw frames and telemetry:** short retention by default; retain around novelty, failures, important events, large prediction errors, or explicit human marking.

**Events:** medium retention; summarize or decay repeated low-value events.

**Episodes:** longer retention when useful, novel, significant, or repeatedly referenced.

**Learned facts/models:** persist while confidence and usefulness remain high.

Candidate mechanisms:

- TTL
- recency decay
- access reinforcement
- novelty score
- utility score
- deduplication
- summarization
- consolidation

The goal is useful continuity, not perfect autobiographical recall.

## Higher-level reasoning

### Optional laptop brain

Use laptop-hosted Ollama/Gemma for high-volume, non-deterministic reasoning where latency is not safety-critical.

The Pi remains responsible for sensor acquisition, immediate perception, safety, motor control, reflexes, and basic autonomous behavior.

The laptop can assist with hypotheses, planning, interpretation, memory consolidation, and choosing interesting things to investigate.

### Behavior repertoire

Possible behaviors:

- follow
- explore
- investigate
- retreat
- wait
- seek human
- return
- inspect unexpected stimulus

Reasoning may help choose behaviors, but execution still passes through deterministic safety arbitration.

## Drives and affect

Eventually introduce explicit internal state that changes behavior over time.

Candidates:

- curiosity
- caution / fear
- social interest
- energy conservation
- novelty seeking
- confidence

For example:

```text
high curiosity + low perceived danger
→ investigate novel object

high caution + repeated collision events
→ reduce exploration speed

low battery
→ suppress curiosity-driven wandering
```

These should be actual state variables rather than role-play prose.

## Audio and social interaction

Potential future work:

- stereo microphones
- sound direction
- sound-event detection
- orienting toward interesting sounds
- speech input
- synthesized responses

## Longer-term experiments

- object detection
- person following
- visual place recognition
- crude mapping
- return-to-location behavior
- novelty detection
- learned motion model
- self-calibration
- episodic replay
- sleep/consolidation cycle
- hypothesis → prediction → outcome → revision
- multiple competing goals
- visible “why did I do that?” causal trace
- autonomous anomaly investigation
- IR illumination / night exploration
- additional cameras when a concrete perception problem justifies them
- commentary/personality generated from actual internal state

## Architectural constraints

1. **Safety-critical behavior stays deterministic.**
2. **LLMs never directly control actuators.**
3. **Unknown sensor values remain unknown.**
4. **Intent, command, measurement, and outcome remain distinct.**
5. **Autonomous behavior is observable and recordable.**
6. **The Pi remains safe if the laptop or network disappears.**
7. **Memory earns its storage; raw experience may expire.**
8. **Prefer simple behaviors that actually work over simulated intelligence that merely sounds impressive.**

The desired end state is not a car with a chatbot.

It is a small machine that senses, acts, remembers, predicts, learns from discrepancies, develops useful preferences, and can explain enough of its causal history that its increasingly strange little decisions remain debuggable.
