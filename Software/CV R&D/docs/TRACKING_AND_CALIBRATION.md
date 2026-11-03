# Tracking and Calibration - v0.2

## Startup

Stand in a neutral forward-facing pose for about one second. Keep wrists comfortably straight. The system establishes face/head neutral and wrist-orientation neutral independently.

## Hotkeys

- `c`: reset face/head neutral
- `w`: reset wrist neutral
- `r`: reset smoothing, IK warm-start, and simulation motion state
- `e`: toggle an obvious eye sweep

## Eyes

MediaPipe blendshape gaze coefficients are not calibrated physical eye angles. Configurable gains/deadzones map them into the published InMoov eye ranges. v0.2 increases the default visual gain and prints commanded angles in the preview.

## Torso

The body tracker forms a torso-local orthonormal basis from shoulders and hips.

- shoulder-line heading -> torso yaw
- lateral tilt of torso-up -> current `topStom` side lean
- sagittal forward/back tilt -> tracked-only diagnostic

This avoids mapping a human movement onto the wrong robot axis.

## Wrists

Hand world landmarks build a palm basis. The palm normal is projected about the forearm axis to estimate pronation/supination. Because camera and hand-model conventions may differ between setups, left/right signs remain configurable in `config/default.json`.
