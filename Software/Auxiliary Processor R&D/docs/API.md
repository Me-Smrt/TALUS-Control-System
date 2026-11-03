# Auxiliary local API

Default: `127.0.0.1:8770`. A non-loopback bind requires `AUTOMATON_AUX_API_TOKEN`.

Read-only/status endpoints:
- `GET /v1/health`
- `GET /v1/status`
- `GET /v1/voices`
- `GET /v1/contract`
- `GET /v1/people/status`

Conversation / voice endpoints:
- `POST /v1/voices/select`
- `POST /v1/tts/synthesize` -> `audio/wav`
- `POST /v1/conversation/text`
- `POST /v1/conversation/reset`
- `POST /v1/vision/ask`

Local person-memory endpoints:
- `POST /v1/people/enroll` with a chosen display name. Enrollment samples the current Pi-owned camera frame; no raw enrollment image is retained.
- `POST /v1/people/remember` stores a short explicit memory for the currently recognized person.
- `POST /v1/people/forget_current` removes the currently recognized person's local identity/memory record.

The dashboard should proxy these server-side so browser JavaScript never receives the auxiliary bearer token. Face recognition is for personalization/session continuity, not authentication or access control.
