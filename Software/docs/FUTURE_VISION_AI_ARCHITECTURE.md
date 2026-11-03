# Future Computer Vision + Auxiliary AI Architecture

This document records the intended extension boundary for the next project phase. It does not freeze a specific camera, Jetson model, IPC framework, STT engine, TTS engine, or local language model yet.

## Design principle

Computer vision and conversational AI should be able to fail, restart, lag, or disappear without owning the hardware watchdogs or bypassing the robot's safety state machines.

The Raspberry Pi 5 remains the robot's deterministic hardware-control/orchestration computer. A future Jetson-class computer is an auxiliary compute node.

## Recommended compute split

```text
                     camera(s)
                        |
                        v
              +-------------------+
              | Raspberry Pi 5    |
              |                   |
              | CV / perception   |
              | robot state       |
              | behavior planner  |
              | motion validation |
              | hardware runtime  |
              +---------+---------+
                        |
            Ethernet / message API
                        |
              +---------v---------+
              | Auxiliary AI node |
              | Jetson-class      |
              |                   |
              | local LLM         |
              | STT               |
              | TTS               |
              | heavier ML        |
              +-------------------+

Pi hardware runtime:
    CCB Supervisor UART + heartbeat
    8 x SocketCAN RCB channels

RCBs:
    local servo limits/timing/safety
```

## Ownership boundaries

### Hardware-control process on the Pi

One process should own:

- CCB Supervisor UART session;
- dedicated Pi->Supervisor heartbeat GPIO;
- all eight SocketCAN control sessions;
- RCB heartbeat cadence;
- registry/topology validation;
- arm/disarm state;
- actuator command validation;
- final conversion from logical motion goals to RCB commands.

`automaton.hardware_runtime.RobotHardwareRuntime` is the beginning of this ownership boundary.

### Computer vision

CV should publish observations such as:

```text
face_detected
face_track = (x, y, confidence)
person_pose
object detections
gaze target
hand position
scene events
```

CV should not write raw PCA9685 registers or directly assert RCB/CCB safety outputs.

A head-tracking behavior, for example, should look conceptually like:

```text
camera frame
  -> face tracker
  -> target direction
  -> behavior/orchestration layer
  -> validated head/eye goals
  -> motion controller
  -> RCB normalized commands
```

This keeps perception errors away from electrical safety authority.

### Auxiliary AI computer

The Jetson-class node should be treated as a service provider, not a motor controller.

Good responsibilities include:

- local language model inference;
- speech-to-text;
- text-to-speech;
- embeddings/memory retrieval;
- computationally heavier vision models if useful later;
- higher-level conversational intent generation.

It can return high-level intents such as:

```text
speak(text)
look_at(person_id)
wave(side="right")
set_expression("curious")
```

The Pi then decides whether the requested behavior is currently legal and maps it to motion. The auxiliary computer should not receive credentials or device access that lets it bypass the Pi control plane.

## Failure behavior

The architecture should remain safe under at least these cases:

| Failure | Desired behavior |
|---|---|
| CV process crashes | Hardware control continues; perception-dependent behaviors stop. |
| LLM/STT/TTS node disconnects | Robot remains locally controllable; conversation features become unavailable. |
| AI response stalls | Heartbeats remain unaffected because they are owned by the hardware-control process. |
| Pi behavior process crashes | Lower-level CCB/RCB watchdogs revoke actuation permission. |
| Ethernet to AI node fails | No direct effect on hardware authorization. |
| Bad/high-risk AI motion request | Pi validation rejects or clamps the request before it reaches an RCB. |

## Inter-process interface direction

Do not freeze the transport yet. Good future candidates include:

- local Unix-domain sockets for Pi-local services;
- ZeroMQ;
- gRPC;
- a small typed WebSocket/message protocol;
- ROS 2 only if its broader ecosystem becomes useful enough to justify the complexity.

Whichever transport is chosen, messages should be typed and versioned. Avoid sharing the safety-critical CAN protocol directly with AI/CV processes.

A useful conceptual API boundary is:

```python
robot.observe(...)
robot.look_at(...)
robot.head.jaw.move(...)
robot.speak(...)
robot.behaviors.wave(...)
```

rather than:

```python
send_can(0x150, ...)
write_pca9685(...)
```

## Resource isolation on the Pi

When CV is added, keep hardware liveness independent from frame processing:

- hardware-control event loop/process: high priority, no heavyweight inference;
- CV capture: dedicated thread/process with bounded frame queues;
- perception: may drop old frames instead of accumulating latency;
- behavior layer: consumes latest state, not an unbounded history;
- logging: asynchronous/buffered where practical.

A slow camera model must never delay a 100 ms RCB heartbeat or Supervisor heartbeat/keepalive.

## Networking with the auxiliary computer

Ethernet is the preferred conceptual link because it separates high-bandwidth AI services from the CCB/RCB buses.

Later design should define:

- static/service discovery addressing;
- authentication if the network is not isolated;
- protocol/version handshake;
- health/status heartbeat;
- bounded request deadlines;
- cancellation;
- audio streaming format;
- model capability discovery.

The robot should remain in a known, safe state when the auxiliary node is absent at startup.

## Suggested next CV milestone

A strong first vision milestone is intentionally independent of servo motion:

1. camera abstraction;
2. live frame acquisition with timestamps;
3. face/person detection;
4. optional face tracking ID;
5. normalized image coordinates `[-1,+1]`;
6. visual/debug overlay;
7. publish observations to a small perception API;
8. record/replay test clips so CV can be tested without robot hardware.

After that works, a simulated or development-locked `look_at()` behavior can consume those observations before physical head/eye motion is enabled.
