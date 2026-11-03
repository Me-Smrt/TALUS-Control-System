# Speech selectivity and turn taking

Idle speech is accepted only when the engagement score crosses the configured threshold. Inputs include:

- explicit wake phrase;
- a visible face in Pi PerceptionState;
- head pose roughly toward the robot;
- gaze roughly toward the robot;
- recent active conversation window.

This combines the directional chassis microphone with visual evidence. It is intentionally stricter while idle and relaxed for short follow-up turns after engagement.

## Echo / barge-in

A directional mic does not remove the need for acoustic echo cancellation when the robot speaker is active. v0.1 therefore defaults to rejecting mic input during TTS. The audio interface is separated so a WebRTC/Speex/hardware AEC backend can be inserted later without changing STT or conversation code.
