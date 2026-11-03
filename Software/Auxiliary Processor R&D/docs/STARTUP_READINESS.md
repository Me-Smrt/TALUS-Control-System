# TALUS AUX — Spoken startup readiness gate

The greeting is the *last* part of initialization, not a greeting played as soon as the LLM server starts. It is synthesized at runtime using the **active TTS voice/voice set** (not STT and not a fixed WAV):

> Hello! I'm TALUS. Ready to help wherever I can!

The greeting is an operator signal that conversation input has been enabled, not a guarantee that disconnected robot hardware is operational.

## Modes

- `python main.py --listen` — STT is loaded, microphone input stream is opened, Silero VAD initializes, and TTS is warmed before the greeting plays. The microphone callback deliberately ignores ALL input until the greeting has completely played (including a short acoustic tail); then audio switches to `listening`.
- `python main.py --console` and `python main.py --console --speak` — the greeting plays using the active voice before the first prompt. It is spoken even without `--speak`, since it is a startup confirmation rather than a normal reply.
- `python main.py` — if this starts the live audio loop in your actual `main.py`, the live loop owns the greeting. Otherwise the non-microphone startup path speaks before idle/service operation.
- AUX HTTP `/v1/conversation/text` and `/v1/vision/ask` — return HTTP `503 {"error":"startup_not_ready", "phase":"initializing"|"announcing"|"failed"}` until greeting completes. `/v1/status` exposes `startup.phase` and `startup.ready`. Other status/configuration endpoints can be inspected during startup.

### Failure behavior

If a voice/model is unavailable, microphone/VAD initialization fails, or audio playback errors, TALUS **does not signal ready**. The startup process reports an error instead of silently accepting text/voice while still loading. A greeting is generated only once per successful AUX process start. Restarting TALUS will greet again.

## Installation and testing (current integrated `main.py`)

The startup cue is already wired into the project's main entry point. There is
**no installer step**. For installations that have the newer `main.py` but are
missing its startup dependency, copy these files from the startup dependency
repair archive into the AUX project root, preserving paths:

- `aux_core/startup_ready.py` — the one-shot TTS readiness gate.
- `aux_core/audio_loop.py` — microphone startup gating and greeting playback.
- `tests/test_startup_ready.py` — regression tests against the integrated main
  script (replaces obsolete installer tests).
- `docs/STARTUP_READINESS.md` — this updated guide.

The previous `tools/install_startup_cue.py` is no longer required and can be
removed after this update. Do **not** replace `main.py` with an older revision;
its world-state and engineering integrations are preserved.

From the project root, verify:

```powershell
python -c "from aux_core.startup_ready import StartupReadyGate; print('Startup dependency available')"
python -m pytest -q tests/test_startup_ready.py
python -m pytest -q
python main.py --console --speak
```

After testing console mode, use `python main.py --listen` to validate the full
mic/VAD/STT startup handoff. Test that speech during the greeting is ignored
and that the expected configured voice is heard. If the speaker or microphone
is unavailable, the gate deliberately stays closed.

The old patch-specific `PATCH_NOTES_STARTUP.md` and any local
`main.py.before_startup_cue.bak` are optional historical backups. Archive or
remove them only once the new main script is confirmed working.

This change does not reset engagement state, alter hardware arming, or bypass
safety boundaries.
