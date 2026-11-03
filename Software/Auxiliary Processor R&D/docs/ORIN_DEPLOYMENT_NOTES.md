# Orin deployment notes

The app layer intentionally does not depend on a particular LLM runtime. On an Orin Nano 8 GB, use the current Jetson AI Lab Qwen3.5-4B recipe and expose its OpenAI-compatible API locally.

Use TensorRT for the YOLO detector on the target Jetson. Keep STT/TTS paths independently configurable so models can be moved between CPU/GPU as memory pressure is measured.

The first physical benchmark should record:

- time from end-of-user-speech to transcript;
- time to first LLM token;
- time to first TTS audio;
- peak unified memory;
- sustained temperatures/power;
- visual-query latency with and without YOLO.
