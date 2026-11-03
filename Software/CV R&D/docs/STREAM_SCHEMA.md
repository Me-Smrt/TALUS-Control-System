# Robot / Blender Stream Schema - v0.2

Each UDP packet uses:

```json
{
  "schema": "inmoov.cv_ik.poc.v2",
  "timestamp_s": 123.4,
  "robot": { "...": "authoritative raw CV/IK targets" },
  "simulation": { "...": "servo-profiled visualization copy" },
  "tracking": { "...": "diagnostics" }
}
```

The critical contract is that `robot` and `simulation` are intentionally separate.

- `robot.arms.<side>.joint_angles_rad` is the direct bounded IK result.
- `simulation.arms.<side>.joint_angles_rad` is the velocity/acceleration-limited copy Blender displays.
- `simulation.*.target_*` fields retain the instantaneous target that the profiler is approaching.
- The Blender bridge should never feed simulation corrections back into the IK solver.

Hands now contain:

```json
"hands": {
  "left": {
    "valid": true,
    "curls": {"thumb": 0.0, "index": 0.0, "middle": 0.0, "ring": 0.0, "pinky": 0.0},
    "wrist": {
      "valid": true,
      "rotation_joint_name": "left_wrist_z",
      "bend_joint_name": "i01.leftHand.wrist.001",
      "rotation_rad": 0.0,
      "bend_rad": 0.0
    }
  }
}
```

Torso contains applied yaw/lateral bend plus `tracked_sagittal_lean_rad`, which is diagnostic-only in this URDF.
