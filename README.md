# Cyber Ferret

A Raspberry Pi-based autonomous RC rover with a deliberately layered architecture:

camera → perception → observation → behavior/intent → safety/control loop → body → observation

Current capabilities:

- Browser HUD and WASD manual control
- 50 Hz drive/control loop
- Camera MJPEG stream
- ArUco marker perception
- Autonomous marker-follow mode
- Safe stop when the visual target is lost
- Session recording with frames and JSONL state
- Semantic event detection

## Hardware calibration

Current empirical values:

- Steering center: 99°
- ESC neutral: 1535 µs
- Forward motion begins around 1631 µs
- Forward maximum used: 1665 µs
- Reverse motion begins around 1518 µs
- Reverse maximum used: 1500 µs

Treat these as vehicle-specific calibration values.

## Runtime layout

Recommended Pi layout:

- `~/cyberferret/` — Git working tree
- `~/cyberferret-venv/` — Python environment
- `~/cyberferret-data/` — recorded sessions / future memories

## Run

```bash
source ~/cyberferret-venv/bin/activate
cd ~/cyberferret
uvicorn cyberferret_web:app --host 0.0.0.0 --port 8000
```

Then open the Pi's port 8000 in a browser.

## Safety

Test autonomous changes with the drive wheels elevated first. SPACE is the emergency stop in both MANUAL and FOLLOW modes.

## Near-term roadmap

1. Semantic events
2. Prediction → outcome records
3. ToF / IMU / steering-angle / power telemetry
4. Obstacle reflexes and autonomous exploration
5. Selective local-LLM interpretation
6. Memory consolidation and expiration
7. Drives / affective state
8. Grounded snarky commentary
