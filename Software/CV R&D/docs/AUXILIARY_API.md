# Pi read-only API for dashboard and auxiliary processor

Default local endpoint: `http://127.0.0.1:8766`

The first version is intentionally **read-only**:

- `GET /v1/health`
- `GET /v1/state`
- `GET /v1/perception`
- `GET /v1/cameras`
- `GET /v1/cameras/{camera_id}/frame?view=raw|processed&max_age_ms=N`
- `GET /v1/contract`

Camera delivery is a point-in-time JPEG snapshot.  There is no raw continuous
video endpoint.  JPEG encoding is lazy, so the Pi does not spend CPU compressing
frames unless a client actually requests one.

## LAN / Jetson access

The default binds only to loopback for safe desktop/dashboard development. To
make the endpoint reachable from the Jetson:

1. change `control_api.bind_host` to `0.0.0.0` (or a specific Pi LAN address);
2. set a strong `AUTOMATON_API_TOKEN` environment variable;
3. send `Authorization: Bearer <token>` from the auxiliary node.

The server refuses a non-loopback bind when no token is configured.

For the final robot deployment, put the Pi and auxiliary processor on a trusted
robot network/VLAN and terminate HTTPS/mTLS at a reverse proxy or service mesh if
traffic can leave that trusted link.

## Frame metadata

Snapshot responses include:

- `X-Automaton-Camera`
- `X-Automaton-View`
- `X-Automaton-Frame-Sequence`
- `X-Automaton-Frame-Age-Ms`
- `X-Automaton-Frame-Monotonic-Ns`
- `X-Automaton-Frame-Unix-Ns`

A requested processed frame can temporarily fall back to the raw frame if no
processor is attached to that camera yet. The response then includes
`X-Automaton-Fallback-From: raw`.
