# Automaton Auxiliary Processor R&D v0.3.1

Offline cognition/perception service intended for a Jetson Orin Nano-class auxiliary computer. Development can run on a normal laptop/desktop first.

## Boundary

The auxiliary node can understand speech, reason, inspect requested camera snapshots, detect objects, synthesize speech, and use curated offline institutional knowledge. It is **not** the robot safety authority and has no direct CAN/PWM/servo interface. The Raspberry Pi remains the control-plane authority.

## Current pieces

- managed local llama.cpp server for Qwen3.5-4B GGUF + multimodal projector
- fast conversational + on-demand deep-reasoning profiles
- editable `config/system_prompt.txt`
- hard-coded spoken progress cues during long reasoning
- local SQLite/FTS5 RAG knowledge base for Tennessee Tech / other curated offline information
- Faster-Whisper local-path STT adapter
- optional Silero VAD microphone loop
- YOLO local detector adapter
- Kokoro local TTS + Piper CLI TTS backends
- speech-only Markdown/URL/code normalization so display formatting is not read aloud
- swappable voice registry with persistent active voice
- engagement scoring from wake phrase + Pi face/head/gaze state
- bounded short-term conversation history
- priority inference scheduler
- Pi snapshot/state client
- local authenticated HTTP API for dashboard integration

No model is downloaded automatically. See `docs/MODELS.md`.

## Laptop setup

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

All Python dependencies are now intentionally kept in the single `requirements.txt`. The older grouped requirements files are compatibility wrappers.

On Python 3.13, the stable PyPI Kokoro/Misaki metadata is still too restrictive, so `requirements.txt` installs their current upstream source trees instead. Python 3.12 remains the most conservative environment if a future source dependency causes trouble.

With the Qwen GGUF pair and `runtime/llama-server.exe` already present:

```powershell
python main.py --console
```

Text + TTS test:

```powershell
python main.py --console --speak
```

Console helpers:

```text
/say <text>          TTS only
/vision <question>   force Pi camera request
/think <question>    force deep reasoning
/fast <question>     force low-latency reasoning
/quit                exit
```

## Offline Tennessee Tech knowledge

Place curated official material under `knowledge/sources/`, then build the local database once:

```powershell
python tools\build_knowledge_base.py
```

The runtime does not crawl the web. See `knowledge/README.md` and `docs/REASONING_AND_KNOWLEDGE.md`.

## Voice API

- `GET /v1/voices`
- `POST /v1/voices/select` `{"voice_id":"kokoro_af_heart"}`
- `POST /v1/tts/synthesize` `{"text":"Hello","voice_id":"kokoro_af_heart"}` -> WAV

## Audio caveat

True acoustic echo cancellation is hardware/driver gated and is not faked. Until it is validated, the live audio loop conservatively ignores queued microphone audio produced while the robot is speaking.
