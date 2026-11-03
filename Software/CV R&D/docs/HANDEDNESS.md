# Camera handedness and mirroring

TALUS treats three different operations separately:

1. `camera.input_mirrored`: normalize a camera/driver that actually delivers mirrored pixels. Default `false`. This is a per-camera calibration value, not an operating-system rule.
2. `camera.mirror_preview`: mirror only the operator preview so it behaves like a bathroom mirror. It must not change CV/IK semantics.
3. `retarget.mirror_motion`: intentionally swap/mirror human motion onto the robot. This is a behavior choice and is independent of camera capture and preview.

All downstream perception uses anatomical left/right from the tracked person. The preview labels `L`/`R` and `L HAND`/`R HAND` mean the person's anatomical side, even when the preview itself is mirrored.

## Calibration

Start with `input_mirrored=false`, `mirror_preview=true`, and `mirror_motion=false`. Raise your anatomical left hand and verify that the preview labels it `L HAND`. Close/move your anatomical left eye and verify the `L` eye marker follows that eye. If the *anatomical labels themselves* are reversed, set `input_mirrored=true` for that camera and repeat. Do not choose this setting based only on Windows vs Linux.
