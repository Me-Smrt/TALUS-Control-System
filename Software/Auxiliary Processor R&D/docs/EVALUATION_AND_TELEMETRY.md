# Evaluation & Telemetry

TALUS records local R&D telemetry to `runtime/telemetry/turns.jsonl`. Nothing is uploaded.

## Conversation telemetry

Each completed turn records operator-facing measurements including reasoning mode, input/output language, total turn latency, RAG usage/sources, vision use/timing, and LLM timing/token throughput. Token counts use backend-reported OpenAI `usage` data when available and a clearly-marked estimate otherwise.

The Aux API exposes rolling aggregates at `GET /v1/telemetry`. The dashboard displays a compact rolling window (default: last 100 turns).

## STT evaluation without a microphone

Use synthetic TTS -> STT as a repeatable baseline:

```powershell
python tools\stt_eval.py
```

This generates one locally synthesized sample per configured test language using `best_available`, transcribes it with Faster-Whisper, and reports language detection, word error rate (WER), character error rate (CER), transcription time, and real-time factor (RTF).

Useful options:

```powershell
python tools\stt_eval.py --languages en,es,fr,de,ja,zh
python tools\stt_eval.py --keep-audio
python tools\stt_eval.py --audio .\sample.wav --expected "Hello TALUS" --language en
```

Synthetic audio is intentionally a baseline, not a substitute for human/microphone testing. TTS audio is cleaner and more regular than real speech. Once a microphone is available, keep the same evaluator and add human recordings with different speakers, distances, rooms, accents, glasses/face tests, and background noise.

The latest report is written to `runtime/telemetry/stt_eval_latest.json`; aggregate STT evaluation measurements also feed `GET /v1/telemetry`.
