# Temporal observation and semantic behavior API (v0.4)

The Pi CV process owns temporal camera sampling and the semantic behavior boundary.

`GET /v1/cameras/{camera_id}/observe` returns a bounded ZIP containing `manifest.json` plus chronological JPEG frames. Sampling uses the Pi's existing frame store; it does not open another camera or run a second scene-language model.

The manifest includes compact synchronized MediaPipe body/head/hand metadata. RGB-D depth is explicitly marked unavailable until a calibrated depth source is integrated.

`POST /v1/behaviors` accepts only validated high-level `BehaviorIntent` requests. Direct actuator fields (PWM, CAN, raw joint angles/trajectories, servo power, etc.) are rejected. The default `BehaviorBroker` is planning-only and returns `executed=false` until a deterministic `MotionController` backend is intentionally attached.

This CV service remains above the safety-critical Pi hardware/CAN owner; it does not open competing CAN/UART sessions.
