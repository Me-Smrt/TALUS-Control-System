# Manual model setup

This repository intentionally **does not download large model weights at runtime**. Download each model once, place it at the configured path, and the service uses only local assets during normal operation.

## 1. LLM / VLM — Qwen3.5-4B GGUF

Current desktop R&D paths:

```text
models/qwen/Qwen3.5-4B-Q4_K_M.gguf
models/qwen/mmproj-Qwen3.5-4B-BF16.gguf
runtime/llama-server.exe   # Windows laptop build
```

`main.py` manages llama.cpp automatically unless `--no-llm-server` is supplied. The application talks to llama.cpp through the local OpenAI-compatible endpoint at `http://127.0.0.1:8000/v1`.

The managed server runs `--reasoning auto`; each request then selects the fast or deep Qwen profile. See `docs/REASONING_AND_KNOWLEDGE.md`.

Upstream model / deployment references:

- https://huggingface.co/Qwen/Qwen3.5-4B
- https://www.jetson-ai-lab.com/models/qwen3-5-4b/
- https://github.com/ggml-org/llama.cpp

For the eventual Orin Nano target, use the Jetson-specific quantized/runtime path rather than assuming the desktop llama.cpp build is the final deployment runtime.

## 2. STT — Faster-Whisper large-v3-turbo

Place the complete CTranslate2 model directory at:

```text
models/faster-whisper-large-v3-turbo/
```

Sources:

- https://huggingface.co/mobiuslabsgmbh/faster-whisper-large-v3-turbo
- https://github.com/SYSTRAN/faster-whisper

The adapter passes `local_files_only=True`; it never falls back to a Hub download during robot operation.

## 3. TTS — Kokoro-82M

Install the Python runtime in the project's active virtual environment:

```powershell
pip install -r requirements.txt
```

Then keep the shared local model files at:

```text
models/kokoro/config.json
models/kokoro/kokoro-v1_0.pth
models/kokoro/voices/<voice>.pt
```

Sources:

- https://huggingface.co/hexgrad/Kokoro-82M
- https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md
- https://github.com/hexgrad/kokoro

Having the `.pth` and `.pt` files alone is not sufficient; the `kokoro` Python package and its runtime dependencies must also be installed.

## 4. TTS multilingual fallback — Piper

Piper voices are local ONNX + JSON pairs. Put selected voices under `models/piper/`, add one registry entry per voice to `config/voices.json`, and make sure the `piper` executable is available.

Voice catalog:

- https://huggingface.co/rhasspy/piper-voices

## 5. Fast object detector — YOLO26n

Default local path:

```text
models/yolo/yolo26n.pt
```

Model documentation:

- https://docs.ultralytics.com/models/yolo26/
- https://docs.ultralytics.com/guides/nvidia-jetson/

On the final Jetson, export/build the TensorRT engine on the target Jetson/JetPack combination.

## Verify local assets and dependencies

```powershell
python tools\check_models.py
```

This inspects local paths/dependencies only; it does not download anything.


## Python dependencies / Python 3.13

Install all Python dependencies with one command:

```powershell
pip install -r requirements.txt
```

The PyPI metadata for Kokoro 0.9.4 and Misaki 0.9.4 excludes Python 3.13. The upstream source trees currently declare support through Python <3.14, so the unified requirements file uses PyPI on Python 3.10-3.12 and the upstream Git repositories on Python 3.13. This requires Git and internet access during setup only; model inference remains offline afterwards.

## Spoken Markdown

LLM responses are preserved exactly for display, but the text passed to TTS is normalized. Markdown emphasis markers, headings, links, table pipes, and similar presentation syntax are removed. Fenced code is skipped by default instead of being read character-by-character. Configure this under `tts.speech_text` in `config/default.json`.

## Optional local face recognition

Persistent person naming/memory uses OpenCV YuNet + SFace. Presence-based context reset does not require these models.

```powershell
mkdir models\face -ErrorAction SilentlyContinue
hf download opencv/face_detection_yunet face_detection_yunet_2023mar.onnx --local-dir models/face
hf download opencv/face_recognition_sface face_recognition_sface_2021dec.onnx --local-dir models/face
```

See `docs/PERSON_IDENTITY.md` for enrollment, privacy boundaries, and database limits.


## Optional multilingual Piper voices

TALUS keeps model installation explicit; runtime startup never downloads voice
weights. The configured optional Piper coverage is German, Korean, Arabic,
Russian, Dutch, Polish, Turkish, Ukrainian, Indonesian, and Vietnamese.

After installing Python dependencies, download the four most useful additions:

```powershell
python tools\download_common_voices.py --core
```

Or download every configured optional Piper voice:

```powershell
python tools\download_common_voices.py --all
```

Specific languages can also be selected, for example:

```powershell
python tools\download_common_voices.py de ko ar ru
```

Then verify all local assets:

```powershell
python tools\check_models.py
```

Kokoro remains preferred for languages where a native Kokoro voice is
configured. Piper fills languages that Kokoro does not currently cover.
Japanese and Mandarin Kokoro frontends require the `misaki[ja,zh]` extras,
which are included by the project requirements.
