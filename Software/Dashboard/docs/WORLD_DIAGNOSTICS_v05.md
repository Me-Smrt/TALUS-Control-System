# Robot dashboard — world and collision diagnostics

The **Robot** page now shows a world-state panel plus a collision/simulation panel.

Authenticated read-only proxies:

- `/api/aux/world` → AUX `/v1/world`
- `/api/robot/world` → Pi `/v1/world`

These use existing token-aware API proxy helpers and login protection. The browser polls roughly every 2.5 seconds (a cheap JSON status request, not new video inference). Rendered detector names are assigned with DOM text, not HTML interpolation.

The panels distinguish recent anonymous image-space detections from last-seen tracks and show capture age, detector inference time, approximate clearance and simulation-only gestures. If AUX or Pi is offline, unavailable status is shown; the dashboard does not invent device readiness or actuator safety. Do not treat green/clear geometric state as physical servo authorization.
