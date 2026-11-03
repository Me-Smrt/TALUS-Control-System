# TALUS AEC / Barge-In v0.6.3 hardening notes

This revision focuses on false interruption containment rather than making the
canceller more aggressive.

## New safeguards

- Reject a barge candidate when the adaptive residual is implausibly louder than
  the raw microphone signal (`residual_unstable`).
- Require a minimum raw microphone level for barge-in, separate from residual
  energy.
- Reject cases where the far-end reference overwhelmingly dominates the raw mic.
- Run an additional post-STT barge-in speech-quality gate. Ordinary microphone
  turns remain more permissive than interruptions.
- A barge-in that transcribes to only TALUS wake/address aliases is treated as an
  attention hold: stop speaking and listen for the follow-up, but do not send an
  empty wake-only turn to Qwen.
- Ctrl+C is an intentional shutdown and no longer prints `[AUX AUDIO FATAL]`.

These thresholds remain R&D defaults. Real robot servo acoustics and final mic
placement will require another calibration pass.
