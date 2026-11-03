# TALUS Visual Grounding

The Aux action router requests current camera data for questions concerning
visible objects, hand poses, gestures, and the robot's surroundings. In
particular, questions such as "what number am I showing on my hand in binary?"
**must not** be answered from linguistic context alone.

Every conversational turn now exposes a `visual_grounding` object in the
returned response, turn telemetry, and action state:

- `status`: `NOT_REQUESTED`, `CURRENT_IMAGE`, `CURRENT_SEQUENCE`,
  `STATIC_ONLY`, or `UNAVAILABLE`. A temporal response requires at least two
  images; a one-frame temporal result is considered `STATIC_ONLY`.
- `camera_id`: Pi-reported camera name (null if no image was acquired).
- `received_at_utc`: approximate AUX reception time for the image(s), not a
  hardware shutter timestamp.
- `age_ms_at_prompt`: time since AUX received the frame(s), sampled when
  constructing the prompt. This is **not** the absolute sensor-frame age.
- `frame_count`: images supplied to the semantic model.

The Pi client separately requests a maximum allowable frame age for still
camera frames (`pi.max_frame_age_ms`). AUX cannot independently attest to the
physical capture timestamp without further Pi metadata.

When no requested camera image is available, AUX returns a deterministic
limitation message without asking Qwen to guess. If a multi-frame temporal
observation fails and the fallback camera supplies only one image, AUX also
returns a deterministic limitation message because one image cannot establish
motion. Spatial/mirroring behavior intents are not submitted to the Pi when
required visual evidence is unavailable.

The code does **not** claim that an acquired image guarantees an accurate
interpretation. Visual reasoning is still probabilistic; physical motion
continues to require Pi-side validation and all existing safety interlocks.

## Validation

```powershell
python -m pytest -q tests/test_visual_grounding.py
python -m pytest -q
python -m compileall -q aux_core tests main.py
```

Live tests should include: showing a binary finger number, temporarily
unplugging the camera during a visual question, and requesting motion
recognition when only a static camera endpoint is available.
