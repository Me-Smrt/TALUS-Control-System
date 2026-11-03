# Temporal perception and semantic behavior boundary (v0.5.5)

TALUS now supports bounded temporal observations without giving the auxiliary LLM direct actuator access.

## Temporal observation

The Aux can request `GET /v1/cameras/{camera_id}/observe` from the Pi CV service. The Pi samples a small number of already-owned camera frames (default 5 over about 1.6 s), attaches compact synchronized pose metadata, and returns a ZIP. It does not expose a continuous raw-video stream.

The Aux creates a chronological contact sheet for the existing single-image multimodal Qwen API and adds deterministic trajectory cues from pose landmarks. These cues help with questions such as "What does it look like I'm doing?" while remaining explicit that pose motion is not itself an activity label.

Console R&D command:

    /observe <question>

Temporal motion questions are also routed automatically and normally use deep reasoning. `/fast` remains an explicit latency override.

## Behavior intents

The Aux action router may emit semantic intents such as:

- `point_at`
- `look_at`
- `gesture`
- `express`
- `mirror_pose`
- `stop_behavior`

The Pi validates these through `BehaviorBroker`. The R&D broker is planning-only by default and cannot translate an intent to PWM, CAN, servo power, arming, or joint commands. Direct-control fields are rejected at the API boundary.

A future deterministic `MotionController` can be attached beneath this boundary. It is responsible for robot state, limits, trajectories, IK, visual/depth verification, retries, and cancellation. The LLM remains a goal/intent planner, not a servo controller.

## Depth

The current temporal manifest reports RGB-D depth as unavailable. MediaPipe world landmarks are not treated as camera depth. The manifest and behavior verification values reserve a clean path for a future calibrated RGB-D source.
