# IK and Retargeting Method - v0.2

The arm-position solver remains the same bounded URDF-style four-DOF chain used in v0.1:

1. shoulder Y
2. shoulder X
3. shoulder Z
4. elbow X

Human upper-arm/forearm directions are measured from MediaPipe pose world landmarks and rescaled to the InMoov segment lengths. A damped least-squares solver finds joint values within the published limits.

## Wrist orientation is separate

Wrist orientation does **not** change the arm-position IK objective.

After the arm solver determines the elbow/wrist position, the hand tracker estimates:

- axial wrist rotation from the palm normal around the forearm axis;
- wrist bend from forearm-to-palm direction.

A short startup neutral calibration removes camera/subject rest offsets. Press `w` to repeat it.

The maintained model currently allows axial rotation in both directions but wrist bend only in the 0..90 deg direction. Opposite human extension is retained as a diagnostic instead of being fabricated.

## Simulation motion is not IK

The simulation motion profiler runs after retargeting. It copies raw targets and approaches them with finite velocity and acceleration. Raw targets remain available unchanged under `frame.robot`.
