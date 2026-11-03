# Sources, Provenance, and Limits - v0.2

The upper-body geometry and joint limits are based on the maintained Sentience Robotics InMoov Xacro used by the supplied Blender builder. `config/inmoov_kinematics.json` stores the evaluated values used by the local proof of concept.

Important modeled ranges used here include:

- wrist axial rotation: -90..+90 deg
- wrist bend: 0..90 deg
- topStom lateral bend: approximately -15..+15 deg
- midStom yaw: approximately -90..+90 deg
- eye pan: approximately -20..+20 deg
- eye tilt: approximately -45..+45 deg

The source Xacro assigns a nominal velocity limit of 0.78540 rad/s (45 deg/s) to these modeled revolute joints. v0.2 uses that as a conservative simulation default.

These remain **model limits**, not final measured limits of the user's physical robot. Actual servo horns, gears, tendons, printed clearances, load, backlash, and installed endpoints must be calibrated on real hardware before these numbers are treated as safe actuator limits.

The synthetic standing legs remain excluded from robot kinematics in this phase.
