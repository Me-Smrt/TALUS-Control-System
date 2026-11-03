# Blender Bridge - v0.3

Run `blender/inmoov_blender_bridge.py` inside Blender.

The bridge is a renderer/adapter only. It does not solve inverse kinematics. It applies externally solved joint angles to the actual source URDF bones in `InMoov_AnimationRig`.

## Required binding

Fresh models should be generated with:

`builder/build_inmoov_complete.py`

That builder leaves upper-body geometry bound to the real source-FK hierarchy. The cleaned project no longer carries the temporary v3.9 migration scripts; rebuild legacy models with the current builder.

## What the bridge drives

- torso source controls
- head/neck source controls
- independent eye pan/tilt source controls
- jaw
- four arm IK joint outputs per side
- axial wrist rotation and modeled wrist bend
- source finger joints from normalized curl

The bridge prefers `packet.simulation` when present and falls back to `packet.robot` for older recordings.

## Eye diagnostics

Press `e` in the CV preview for an obvious gaze sweep, or run:

```powershell
python tools\blender_motion_diagnostic.py eyes
```

The rig custom properties also expose `CV_EYE_*_DEG` values so movement can be verified numerically even when it is visually subtle.

## Torso diagnostics

Run:

```powershell
python tools\blender_motion_diagnostic.py torso
```

The current `topStom` source axis represents lateral/side lean. Sagittal forward/back lean is tracked but not rendered onto another fake DOF.
