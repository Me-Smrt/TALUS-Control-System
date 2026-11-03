# TALUS AUX v0.7 — Deterministic world state and engineering RAG

## Architecture

- Pi is still the authority for camera and MediaPipe pose; AUX polls Pi's bounded `/v1/cameras/<id>/frame` endpoint every `world_state.poll_period_s` (default 3 seconds) after spoken startup readiness.
- AUX runs the *existing* YOLO model, serializing model accesses with a lock. The low-rate worker does not run Qwen or face recognition. It assigns short-lived anonymous `person_N` and `object_N` IDs by class + bounding-box overlap (not biometric identity); IDs can swap across occlusions or crossings.
- The bounded in-memory world cache is exposed at authenticated `GET /v1/world`. It includes image-space boxes, capture-based freshness, movement in pixels, sample count, inference latency, and errors. It does not store image files or claim physical 3D coordinates.
- The conversation injects a small world summary only on relevant queries. Qwen does *not* have persistent mutable awareness; it receives a timestamped read-only snapshot. Live camera imagery remains required for precise current visual questions.
- TTL distinguishes `current` from `last_seen`, and old tracks expire. Objects unseen since the last observation are *not* guaranteed to remain in place.

## Configuration

`config/default.json` includes `world_state.enabled`, `poll_period_s`, `current_ms`, `retention_ms`, `max_tracks` and `vision.detector.image_size`. Set `world_state.enabled=false` on constrained CPUs if needed. The background observer will not run without a Pi camera or installed YOLO weights. When `--console` starts, the readiness greeting finishes first.

## Engineering knowledge

A separate technical FTS5 DB lives at `runtime/engineering.sqlite3`; it is never mixed into the Tennessee Tech knowledge database. This update includes a small, checked Y–Δ resistor transformation reference, and a deterministic query-term grounding rule even if the engineering DB is not built.

To add more reliable local engineering knowledge, place licensed/verified `.md`, `.txt`, `.html`, `.csv`, or `.json` material in `knowledge/engineering` with optional source metadata, and rebuild:

`python tools/build_knowledge_base.py --source-dir knowledge/engineering --db runtime/engineering.sqlite3`

No automatic browsing or document downloading is performed. Imported documents should be reviewed for accuracy, licensing, and prompt injection.

## Tests and limitations

`python -m pytest -q tests` verifies current code without a running YOLO, GPU, physical Pi, or audio. Validate real object detections through `GET /v1/world` and the dashboard. ID matching is lightweight and does not solve multi-person speaker association; it may swap IDs when people cross. For stronger identity permanence and action recognition we would need later tracker/camera calibration improvements.
