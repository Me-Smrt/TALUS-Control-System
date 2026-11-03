# Raspberry Pi control-plane architecture — v0.3

The Raspberry Pi owns time-sensitive robot state and physical I/O.  The future
Jetson Orin Nano (or another accelerator) is a replaceable auxiliary inference
node, not an actuator controller.

```text
USB / RGB-D cameras ─┐
USB microphone ──────┤
USB speaker ─────────┤
                     v
               Raspberry Pi 5
        ┌──────────────────────────┐
        │ camera ownership         │
        │ MediaPipe fast tracking  │
        │ PerceptionState          │
        │ InMoov IK                │
        │ motion shaping           │
        │ RobotState / Health      │
        │ CCB + RCB control*       │
        └──────────┬───────────────┘
                   │ Ethernet
                   v
          auxiliary inference node
          object/VLM/LLM/STT/TTS
```

`*` The existing CCB/RCB host package remains the safety-critical hardware
owner.  v0.3 exposes placeholders for its state, but does not fake hardware
health while boards are unavailable.

## State layers

- **PerceptionState** preserves the full latest face/body/hand result with source
  camera and capture timestamps.
- **RobotState** is a compact dashboard-oriented snapshot containing system
  health, safety status, control-node status, cameras, audio, perception summary,
  motion summary, and auxiliary-node status.
- Every externally useful observation carries monotonic and/or Unix nanosecond
  timestamps.  Monotonic time is used for freshness/timeout logic; Unix time is
  for logs/UI correlation.

## Authority boundary

The auxiliary computer may eventually request high-level intents such as
`look_at`, `gesture`, or `speak`. It must never own CAN sessions, CCB Supervisor
UART, raw PWM, arm/disarm permission, or the RCB watchdog heartbeat.

The high-level intent contract is reserved in `inmoov_pi/contracts.py` for the
next R&D phase.
