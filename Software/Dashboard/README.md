# ARC Robotics Dashboard v0.5

Locally hosted Flask dashboard for the Automaton/InMoov robotics project. v0.5
preserves the existing visual shell, authentication model, circuit background, and
page structure while hardening the interface for responsive camera/status use.


## v0.4 auxiliary voice pass

- authenticated auxiliary-runtime status panel;
- swappable local TTS voice selector backed by the auxiliary voice registry;
- authenticated **Listen to this** sample synthesis and in-browser WAV playback;
- auxiliary API credentials remain server-side in Flask;
- voice/TTS controls remain presentation/configuration features, not robot safety controls.

## v0.3 responsive/browser pass

- camera frames are strictly bounded to their panel and can no longer force a grid
  column wider than the available viewport;
- camera images fill a responsive aspect-ratio container with `object-fit: contain`;
- camera and Raw/Processed selectors wrap instead of disappearing off-screen;
- phone controls use >=44 px touch targets;
- primary navigation remains available on tablets/phones as a horizontally
  scrollable second header row instead of being hidden;
- dashboard cards collapse from 4 -> 2 -> 1 columns as space decreases;
- node tables remain usable on narrow displays with contained horizontal scrolling;
- iOS safe-area viewport support and mobile text-size handling are included;
- `-webkit-backdrop-filter` / mask fallbacks and opaque no-blur fallbacks improve
  Safari/Firefox interoperability;
- View Transitions remain progressive enhancement: browsers that do not implement
  them simply perform normal page navigation;
- camera toggle buttons now publish `aria-pressed` state and keyboard focus is
  clearly visible.

The target browser set is current mainstream Chrome/Chromium, Edge, Firefox, and
Safari on desktop, Android, and iOS/iPadOS. No browser-specific feature is required
for core navigation, authentication, robot state, or camera controls.

## Robot-state functionality

- dashboard metrics for Pi health, safety state, fast perception, and auxiliary node;
- combined Pi + auxiliary host telemetry (CPU, memory, disk, temperature, load, process RSS, uptime);
- camera snapshots are double-buffered in the browser so a good frame remains visible until the replacement has decoded;
- browser TTS previews support blob-backed WAV playback under the dashboard CSP;
- Pi-owned camera viewer with camera selector and **Processed / Raw** toggle;
- snapshot polling instead of a continuous raw-video stream;
- primary CCB/RCB node-status map and detailed node table;
- perception, motion, CPU/memory/temp, microphone/speaker, and auxiliary status;
- server-side proxy to the Pi control-plane API so API tokens stay out of browser JS;
- safety-critical dashboard controls intentionally remain disabled during R&D.

## Architecture

```text
Browser
  |
  | authenticated HTTPS/local dashboard
  v
Flask dashboard
  |
  | server-side proxy (token stays here)
  v
Pi control-state API :8766
  |-- RobotState
  |-- PerceptionState
  |-- raw / processed camera snapshots
```

The dashboard is a **presentation layer**, not a safety authority. It cannot arm
hardware or directly command CAN/PWM.

## Pages

- `/` — project overview
- `/login` — secure operator login
- `/dashboard` — live system overview and camera/node surfaces
- `/robot` — detailed safety, perception, I/O, camera, and node status
- `/settings` — authenticated configuration/status surface
- `/help` — state/authority documentation

## First-time setup

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Linux / Raspberry Pi:

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

Copy `.env.example` to `.env`. Generate a strong dashboard secret:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Set `ARC_SECRET_KEY` to that value.

By default the Pi state service is expected at `http://127.0.0.1:8766`. If that
API uses `AUTOMATON_API_TOKEN`, set the same secret as `ARC_ROBOT_API_TOKEN` in
the dashboard environment. It remains server-side and is never emitted to browser
JavaScript.

## Create an operator

```bash
flask --app app create-user operator
```

For local development:

```bash
# .env: ARC_DEV_MODE=1
python app.py
```

For deployment, keep `ARC_DEV_MODE=0`, use HTTPS, set `ARC_TRUSTED_HOSTS`, and
run behind Gunicorn/reverse proxy on the Raspberry Pi.

## Camera viewer

The browser requests `/api/robot/cameras/<id>/frame`. Flask proxies one JPEG
snapshot from the Pi state service. The page refreshes snapshots only while the
operator view is open. The Pi-side service does not provide a continuous raw
stream.

The second planned eye camera can appear before installation; its state remains
disabled/offline rather than being reported as healthy.

## v0.5 metrics / R&D connectivity

The Dashboard page combines Raspberry Pi health from the Pi state API with host/process telemetry from the auxiliary service `GET /v1/health`. Apply the matching Auxiliary Processor R&D v0.3.9 patch so CPU, memory, disk, load, process RSS, and best-effort temperature fields are populated.

During Windows R&D, if the dashboard, Pi CV process, and auxiliary process all run on the same laptop, both API bases may use loopback (`127.0.0.1`). On the deployed robot the dashboard lives on the Pi, so `ARC_ROBOT_API_BASE` can remain loopback while `ARC_AUX_API_BASE` must point to the auxiliary computer's LAN address. The auxiliary API must then be bound to a LAN interface and protected with the same bearer token configured as `ARC_AUX_API_TOKEN`.

The top-level Auxiliary Processor card now treats the dashboard's direct auxiliary API poll as authoritative for reachability. The Pi-reported auxiliary link remains visible separately; this prevents a stale `not_connected` field in Pi state from making a directly reachable auxiliary service appear offline.

Camera snapshots are fetched and decoded off-screen before replacing the visible frame. Transient frame failures therefore leave the last good frame in place instead of flashing the empty-state panel.

## Auxiliary voice integration

The Dashboard page now reads `/api/aux/status` and `/api/aux/voices`, lets an authenticated user select the active local TTS voice, and proxies a short WAV preview through `/api/aux/tts/sample`. The auxiliary bearer token remains server-side in Flask. Set `ARC_AUX_API_BASE` and `ARC_AUX_API_TOKEN` in `.env`.
