# TALUS Acoustic Echo Cancellation and Barge-In (v0.6.1 R&D)

## Purpose

TALUS now keeps the microphone pipeline alive while TTS is playing. The exact
post-trim PCM sent to the speaker is copied into a far-end reference timeline.
A dependency-light adaptive spectral echo canceller estimates the speaker ->
room -> microphone transfer path and subtracts that echo before Silero VAD.

This is the first R&D backend, not a claim of WebRTC AEC3 parity. The interface
is intentionally isolated so the adaptive backend can later be replaced by a
native WebRTC/Speex/OS AEC implementation without changing STT, engagement, or
conversation logic.

## Signal path

```text
Kokoro/Piper PCM
      |--------------------------> ContinuousWavPlayer -> speaker
      +----> EchoReferenceTimeline
                         |
microphone -> AdaptiveEchoCanceller -> residual -> Silero VAD -> STT gate
                                                     |
                                          double-talk confirmed
                                                     |
                                          cancel current TTS
                                                     |
                                       finish user utterance -> STT
```

The microphone/VAD/AEC capture path now runs on its own thread. This is required
for genuine barge-in because the older loop stopped consuming microphone blocks
while Qwen/TTS was busy.

## Safety/conservatism

Barge-in requires all of the following:

1. A real speaker-reference signal is available.
2. The AEC has had its configured warm-up time.
3. Silero identifies speech in the echo-cancelled residual.
4. The residual lasts for the configured confirmation period.
5. Residual level / echo-reduction / correlation checks indicate likely
   near-end double-talk rather than TALUS hearing itself.
6. The completed interruption still passes the normal post-Whisper speech gate.

If AEC is disabled/unavailable and `allow_barge_in_without_aec` remains false,
TALUS keeps the previous safe behavior and ignores microphone input during TTS.

## Debug output

Run:

```powershell
python main.py --listen
```

Startup should include:

```text
[AUX] AEC=adaptive_spectral barge_in=enabled initial_delay=45ms
```

A successful interruption should look approximately like:

```text
[AUX] VAD speech_start source=aec_residual
[AUX] barge_in=confirmed residual=... mic=... ref=... ratio=... corr=... erle=... delay=...ms
[AUX] assistant speech interrupted; listening to barge-in utterance.
[AUX] VAD speech_end duration=... type=barge-in; transcribing...
you> Wait, go back.
[AUX] speech_gate=accepted ...
[AUX] engagement=accepted score=1.00 reason=barge_in
```

A residual that still looks too much like TALUS's own speaker output is rejected
before it can cancel TTS. In debug mode you may see:

```text
[AUX] barge_in=candidate rejected reason=aec_not_converged
```

That is preferable to self-interruption.

## Current configuration

The defaults are under `audio.aec` in `config/default.json`.

Important tuning values:

- `reference_delay_ms`: initial speaker->mic timing estimate.
- `delay_search_max_ms`: range searched for the best reference alignment.
- `warmup_ms`: minimum far-end playback time before interruption is allowed.
- `barge_in.confirm_ms`: residual speech duration before interruption.
- `barge_in.min_residual_rms`: minimum residual audio energy.
- `barge_in.min_residual_to_mic_ratio`: rejects cases where almost everything is
  explained by the speaker echo.
- `barge_in.min_erle_db`: minimum echo reduction when far-end correlation is
  still significant.

Do not tune these aggressively from one laptop-room test. The final robot will
have different speaker/microphone geometry, body reflections, fans/servos, and
mechanical noise.

## Recommended first test

1. Start `python main.py --listen`.
2. Wake TALUS normally.
3. Ask for an answer long enough to keep TTS speaking for several seconds.
4. While TALUS is speaking, say a clear interruption such as:
   `Wait, stop for a second.`
5. Save the full AEC/debug lines around the interruption.
6. Repeat once while staying silent during TALUS speech. TALUS should *not*
   interrupt itself.

The pair of tests matters: successful barge-in is only useful if far-end-only
speech remains stable.

## Real-robot follow-up

When installed in the physical robot, re-run calibration with:

- final microphone position,
- final speaker position and volume,
- servo motion at idle/light/heavy load,
- cooling fans,
- representative room acoustics.

Servo noise is primarily a near-end noise-rejection/VAD/speech-gate problem;
TALUS speaker echo is the AEC problem. Keeping those filters separate lets us
tune one without destabilizing the other.


## v0.6.1 interruption hardening

The first live test exposed two important edge cases and one native-audio race.
v0.6.1 deliberately hardens correctness before making the detector more
aggressive.

### 1. Unconfirmed echo candidates never reach Whisper

In v0.6.0 a Silero event that *started* while TALUS was speaking could later be
marked as `barge-in` even when every double-talk check rejected it. Speaker
leakage could therefore be transcribed into a hallucinated short phrase such as
`TALUS Talus`.

Now a candidate captured during TTS is discarded unless the double-talk gate
actually confirms it:

```text
[AUX] VAD speech_start source=aec_residual
[AUX] barge_in=candidate rejected reason=...
[AUX] barge_in=candidate discarded reason=not_confirmed
```

No STT request is made for that rejected candidate.

### 2. Barge-in requires fresh, sustained AEC evidence

Before TALUS stops speaking, the current playback must now demonstrate:

- reference timeline coverage for the current microphone block,
- fresh echo-path convergence during the **current** TTS utterance,
- a recently verified echo path,
- multiple consecutive blocks of valid double-talk evidence.

A single low-correlation or temporarily misaligned block can no longer cancel
TTS. New optional tuning keys have code defaults and do not require replacing
an existing `config/default.json`:

- `audio.aec.playback_write_block_ms` (default `20`)
- `audio.aec.ready_min_blocks` (default `6`)
- `audio.aec.utterance_ready_min_blocks` (default `3`)
- `audio.aec.ready_min_erle_db` (default `1.5`)
- `audio.aec.ready_min_reference_coverage` (default `0.80`)
- `audio.aec.barge_in.evidence_ms` (default `160`)
- `audio.aec.barge_in.min_reference_coverage` (default `0.80`)
- `audio.aec.barge_in.max_good_echo_age_ms` (default `650`)

These should remain at their defaults until live logs justify changing them.

### 3. PortAudio cancellation is cooperative

v0.6.0 could abort and close the sounddevice/PortAudio stream from the capture
thread while the playback thread was blocked inside `stream.write()`. Native
audio backends are not guaranteed to survive that cross-thread teardown, and a
failure can terminate Python without a normal traceback.

v0.6.1 writes playback in short blocks. `cancel()` only sets a thread-safe
Event; the playback worker notices it within roughly one block and exits on its
own thread. Stream teardown happens later on the normal playback/control path.

The AEC reference is also published block-by-block immediately before playback,
so audio cancelled before reaching the speaker is never inserted as a phantom
future echo reference.

### 4. Worker failures are no longer silent

TTS synthesis/playback worker exceptions now emit `[AUX TTS ERROR] ...`, and a
fatal Python-side live-audio exception emits `[AUX AUDIO FATAL] ...` before the
exception propagates. A native process termination should be far less likely
because of cooperative PortAudio cancellation, but the extra diagnostics make
ordinary Python failures visible.

## v0.6.2 field-tuning changes

- AEC readiness now means the current playback/reference path has been repeatedly aligned. Positive ERLE is retained as a cancellation-quality metric but is no longer required just to arm interruption.
- Reference timeline coverage and reference energy are separate. Natural quiet gaps between spoken words no longer look like a missing reference.
- Barge-in evidence tolerates short neutral far-end gaps instead of resetting on every quiet syllable.
- A conservative strong-near-end override can recognize obvious double-talk before the lightweight spectral canceller has strong ERLE. It requires prior adaptation, low far-end correlation, a strong residual, and a microphone/reference energy margin.
- Streaming TTS can prebuffer a small number of synthesized chunks before first playback. The live audio path defaults to 2 chunks with a bounded timeout, reducing the early "first phrase then pause" artifact while retaining responsiveness for short replies.

The adaptive_spectral backend remains an R&D backend. Keep the diagnostic output enabled during acoustic tuning and expect microphone/speaker/servo placement on the physical robot to require retuning or a later WebRTC AEC3/native backend.
