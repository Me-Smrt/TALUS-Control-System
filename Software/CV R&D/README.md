# InMoov CV + IK / Raspberry Pi Control Plane v0.3

This repository is the current Raspberry Pi-side R&D package for fast vision,
retargeting, InMoov inverse kinematics, Blender visualization, and the first
shared robot/perception state layer.

The normal entry point is still:

```bash
python main.py
```

The existing CV/IK math remains authoritative. v0.3 adds infrastructure around
it; it does not move smoothing or dashboard presentation into the real IK math.

## What v0.3 adds

- `RobotStateHub`: compact shared robot/system state for the dashboard.
- full latest `PerceptionState`: face/body/hand data with source/timestamps.
- Pi system health sampling (CPU, memory, disk, temperature when available).
- camera ownership and a thread-safe latest-frame broker.
- optional second USB camera capture worker.
- **on-demand** raw/processed JPEG endpoints; no continuous raw-video stream.
- read-only HTTP API for the local dashboard and future Jetson Orin Nano.
- planned microphone/speaker state inventory without prematurely freezing STT/TTS transport.
- high-level auxiliary intent contract placeholders; no auxiliary actuator control.
- systemd service example for eventual Pi deployment.

## Current physical plan represented

- Raspberry Pi 5: robot control/perception authority.
- Hiwonder Aurora930 Pro: planned primary RGB-D camera.
- compact USB eye camera: planned second view.
- USB microphone and USB speaker: physically owned by the Pi.
- Jetson Orin Nano-class auxiliary processor: object/scene understanding,
  local AI model, STT, TTS, and other heavier inference.

The Aurora depth/IR SDK is intentionally not implemented before hardware is in
hand. The present OpenCV camera path covers RGB and ordinary development webcams.

## Quick start

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

Linux / Raspberry Pi:

```bash
source .venv/bin/activate
pip install -r requirements.txt
python main.py --no-preview --no-bridge
```

The first run downloads the MediaPipe Holistic task model into `models/`.

## Local state API

By default the read-only API binds only to localhost:

```text
http://127.0.0.1:8766
```

Useful endpoints:

```text
GET /v1/state
GET /v1/perception
GET /v1/cameras
GET /v1/cameras/aurora/frame?view=raw
GET /v1/cameras/aurora/frame?view=processed
GET /v1/contract
```

Try:

```bash
python tools/api_probe.py
```

For eventual Jetson access, use `config/pi_hardware.example.json` as a starting
point and set a strong `AUTOMATON_API_TOKEN`. The API refuses a LAN-visible bind
without authentication.

## Camera behavior

The configured tracking camera feeds MediaPipe and the IK stack. Raw frames are
kept locally in memory; the processed view is the existing CV overlay. Additional
cameras can be captured by the Pi without running MediaPipe on them.

If the dashboard or Jetson asks for a snapshot, the latest requested frame is
JPEG-encoded at that moment. If nobody asks, there is no network image traffic
and no continuous JPEG encoding workload.

The default second camera is disabled until its actual USB index is known.

## Blender

Run:

```text
blender/inmoov_blender_bridge.py
```

inside the generated InMoov `.blend`, then start `main.py`. The builder remains
at:

```text
builder/build_inmoov_complete.py
```

and continues to use source-FK geometry binding so visualization follows the
same joint-angle solution used by the robot model.

## Safety boundary

The state/API layer is descriptive. It does **not** become a new safety layer.
CCB Supervisor + RCB safety logic and the dedicated Pi hardware-control runtime
remain authoritative for arm/disarm, watchdogs, CAN sessions, and servo power.
Until those real hardware signals are integrated, dashboard safety/node fields
are marked `unverified` / `unavailable` rather than fabricated.

The future auxiliary processor is permitted to request high-level behavior only.
It must never directly send raw PWM, CAN frames, servo channel writes, or safety
commands.

## Project layout

```text
main.py
inmoov_cv/                 # CV, retargeting, IK, simulation motion profile
inmoov_pi/                 # state, frame broker, Pi API, health, audio inventory
blender/                   # Blender bridge
builder/                   # corrected InMoov scene builder
config/                    # desktop/default + Pi hardware example
docs/                      # architecture/protocol notes
tests/                     # math + state/API regression tests
tools/                     # diagnostics / replay / API probe
systemd/                   # eventual Pi service example
logs/                      # runtime recordings (ignored by Git)
models/                    # downloaded MediaPipe assets (ignored by Git)
```

## Validation status

This release can be validated without robot hardware: math/state/API unit tests,
Python compilation, configuration parsing, and loopback snapshot delivery.
Actual USB device enumeration, Aurora depth SDK integration, ALSA device names,
and hardware-control-state integration are explicitly bench-gated.

See:

- `docs/PI_CONTROL_ARCHITECTURE.md`
- `docs/AUXILIARY_API.md`
- `docs/CAMERA_AND_AUDIO_PLAN.md`
- `docs/IK_METHOD.md`
- `docs/BLENDER_BRIDGE.md`
