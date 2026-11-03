# Pi CV/IK v0.5 — Collision preview, world state, simulated gestures

## Collision preview (not hardware authorization)

The kinematics are used to calculate shoulder/elbow/wrist positions for each arm in a common torso-local frame. A conservative set of upper-arm / forearm capsules and a wrist/hand sphere approximate the arms. Candidate IK targets are checked against the other arm, including 12 intermediate samples through joint space. A blocked target holds both arms at the previous collision-free target. The simulation profiler independently checks its interpolated output, which Blender consumes. Near misses and block causes are published as `collision` and `simulation_collision` diagnostics under the Pi state `motion.summary`.

These simplified volumes do NOT model fingertip geometry, self-collisions within each arm, torso/head collisions, robot/room collisions, structural compliance, servo offsets, real feedback, or dynamic/continuous time guarantees. Sampled paths can miss collisions between samples. Therefore they are a visual R&D collision preview and must NOT be used as the sole safety control on a real robot. Physical servo motion must remain disabled until a calibrated full-body collision system, hard limits, watchdogs, and hardware safety have been validated.

Config `collision_guard` contains `enabled`, radii, and margin in millimeters. **Do not disable safety checks to force a gesture through.** Measure parts and calibrate volumes in Blender before trusting these parameters.

## World state

`GET /v1/world` reports the Pi's current/stale *primary MediaPipe subject* and robot motion summary; it does not pretend MediaPipe currently tracks multiple primary bodies. AUX YOLO owns anonymous multi-person/object detections.

## Named Blender gestures

The `behavior.mode="simulation_only"` configuration attaches an explicit Blender gesture backend to the existing semantic intent broker. Supported test presets: `wave`, `nod`, `shake_head`; `stop_behavior` cancels. No direct servo/joint commands are accepted from AUX. No hardware controller is attached or reachable from this backend, and `executed` stays false for physical execution. The active preset is injected into `robot_frame` before the existing servo-speed limiter and UDP Blender bridge. The right-arm wave preset is model-limited and swept-collision checked. No inference model chooses raw joint angles.

To test while Pi CV and the Blender bridge are running:

`python tools/test_sim_gesture.py wave`

`python tools/test_sim_gesture.py nod`

`python tools/test_sim_gesture.py shake_head`

The probe checks that `/v1/behaviors` identifies the backend specifically as `blender_simulation_only` and refuses any other backend. This is important because future hardware control may use the same semantic API; this test probe must never accidentally actuate hardware.

The behavior broker returns `simulation_queued`. Look at Blender and the dashboard for visible motion and collision holds. `planning_only` remains the default whenever the simulation backend is not explicitly configured.
