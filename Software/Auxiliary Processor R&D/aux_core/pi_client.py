from __future__ import annotations

import io
import json
import os
import threading
import time
import urllib.parse
import urllib.request
import uuid
import zipfile
from collections.abc import Callable
from typing import Any

from .util import json_request


class PiClient:
    def __init__(self, cfg: dict[str, Any]) -> None:
        base_env = str(cfg.get("base_url_env", "AUTOMATON_PI_API_BASE")).strip()
        configured_base = str(cfg.get("base_url", "http://127.0.0.1:8766"))
        self.base = os.getenv(base_env, configured_base).strip().rstrip("/") if base_env else configured_base.rstrip("/")
        self.timeout = float(cfg.get("timeout_s", 2.0))
        self.max_age_ms = float(cfg.get("max_frame_age_ms", 700))
        default_camera = str(cfg.get("default_camera", "tracking"))
        self.camera_preference = [str(x) for x in cfg.get("visual_camera_preference", [default_camera])]
        self.default_camera = default_camera
        self.token = os.getenv(str(cfg.get("token_env", "AUTOMATON_API_TOKEN")), "").strip()

    def _headers(self, accept: str = "application/json") -> dict[str, str]:
        h = {"Accept": accept}
        if self.token:
            h["Authorization"] = "Bearer " + self.token
        return h

    def health(self) -> dict[str, Any]:
        """Return the Pi control-plane health payload.

        This is intentionally the light-weight reachability probe used by the
        auxiliary process.  It proves Aux -> Pi API connectivity without
        requiring a full robot-state snapshot.
        """
        return json_request(self.base + "/v1/health", headers=self._headers(), timeout=self.timeout)[1]

    def state(self) -> dict[str, Any]:
        return json_request(self.base + "/v1/state", headers=self._headers(), timeout=self.timeout)[1]

    def world(self) -> dict[str, Any]:
        return json_request(self.base + "/v1/world", headers=self._headers(), timeout=self.timeout)[1]

    def perception(self) -> dict[str, Any]:
        return json_request(self.base + "/v1/perception", headers=self._headers(), timeout=self.timeout)[1]

    def cameras(self) -> dict[str, Any]:
        return json_request(self.base + "/v1/cameras", headers=self._headers(), timeout=self.timeout)[1]

    @staticmethod
    def _camera_online(info: dict[str, Any]) -> bool:
        return bool(info.get("enabled", True)) and str(info.get("status", "")).lower() == "online"

    def choose_camera(self) -> str:
        """Choose a live Pi-owned camera without assuming a fixed Linux/device name.

        Preference IDs are tried first.  If the configured names don't match the
        Pi (for example the Pi calls its tracking camera ``aurora`` while the Aux
        config says ``tracking``), fall back to the Pi's reported tracking camera,
        a camera with a published raw frame, or any online camera.  This keeps the
        camera contract semantic and prevents a harmless config rename from
        producing HTTP 503 frame_unavailable responses.
        """
        try:
            payload = self.cameras()
            cams = payload.get("cameras", {}) if isinstance(payload, dict) else {}
            frames = payload.get("frames", {}) if isinstance(payload, dict) else {}
            if not isinstance(cams, dict):
                cams = {}
            if not isinstance(frames, dict):
                frames = {}

            # 1) Explicit preference order.
            for cid in self.camera_preference:
                info = cams.get(cid, {})
                if isinstance(info, dict) and self._camera_online(info):
                    return cid

            # 2) The Pi's authoritative perception/tracking camera ID.
            try:
                snap = self.state()
                tracked = str(snap.get("perception", {}).get("tracking_camera_id") or "").strip()
                if tracked and tracked in cams and self._camera_online(cams.get(tracked, {})):
                    return tracked
            except Exception:
                pass

            # 3) Any camera that is online *and* is already publishing a raw frame.
            for cid, info in cams.items():
                frame_views = frames.get(cid, {}) if isinstance(frames.get(cid, {}), dict) else {}
                if isinstance(info, dict) and self._camera_online(info) and "raw" in frame_views:
                    return str(cid)

            # 4) Any online camera, preferring role=tracking.
            online = [
                (str(cid), info)
                for cid, info in cams.items()
                if isinstance(info, dict) and self._camera_online(info)
            ]
            for cid, info in online:
                if str(info.get("role", "")).lower() == "tracking":
                    return cid
            if online:
                return online[0][0]
        except Exception:
            pass

        # Last-resort deterministic fallback for an unavailable/unreachable Pi.
        return self.default_camera or (self.camera_preference[0] if self.camera_preference else "tracking")

    def frame(self, camera_id: str | None = None, view: str = "raw") -> tuple[bytes, dict[str, str]]:
        camera_id = camera_id or self.choose_camera()
        q = urllib.parse.urlencode({"view": view, "max_age_ms": self.max_age_ms})
        url = f"{self.base}/v1/cameras/{urllib.parse.quote(camera_id, safe='')}/frame?{q}"
        req = urllib.request.Request(url, headers=self._headers("image/jpeg"))
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return r.read(6 * 1024 * 1024), dict(r.headers.items())

    def observe(
        self,
        camera_id: str | None = None,
        *,
        duration_ms: int = 1600,
        samples: int = 5,
        view: str = "raw",
        max_width: int = 640,
    ) -> dict[str, Any]:
        """Request a bounded chronological multi-frame observation from the Pi."""
        camera_id = camera_id or self.choose_camera()
        query = urllib.parse.urlencode({
            "view": view,
            "duration_ms": int(duration_ms),
            "samples": int(samples),
            "max_width": int(max_width),
        })
        url = f"{self.base}/v1/cameras/{urllib.parse.quote(camera_id, safe='')}/observe?{query}"
        req = urllib.request.Request(url, headers=self._headers("application/zip"))
        timeout = max(self.timeout, max(0.0, float(duration_ms) / 1000.0) + self.timeout + 1.0)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(24 * 1024 * 1024)
            headers = dict(r.headers.items())
        with zipfile.ZipFile(io.BytesIO(raw), "r") as zf:
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            frames = []
            for item in manifest.get("frames", []):
                name = str(item.get("file", ""))
                if not name or "/" in name or "\\" in name or name not in zf.namelist():
                    raise ValueError("Invalid temporal observation frame manifest")
                frames.append(zf.read(name))
        return {"manifest": manifest, "frames": frames, "headers": headers}

    def submit_behavior(
        self,
        intent: str,
        parameters: dict[str, Any] | None = None,
        *,
        ttl_ms: int = 5000,
        priority: int = 0,
    ) -> dict[str, Any]:
        """Submit a semantic behavior request; never sends joints/PWM/CAN fields."""
        issued = time.monotonic_ns()
        ttl_ms = max(250, min(15000, int(ttl_ms)))
        payload = {
            "schema": "automaton.aux_intent.v1",
            "intent": str(intent),
            "request_id": str(uuid.uuid4()),
            "issued_monotonic_ns": issued,
            "expires_monotonic_ns": issued + ttl_ms * 1_000_000,
            "ttl_ms": ttl_ms,
            "parameters": dict(parameters or {}),
            "priority": int(priority),
        }
        return json_request(
            self.base + "/v1/behaviors",
            method="POST",
            payload=payload,
            headers=self._headers(),
            timeout=max(self.timeout, 3.0),
        )[1]


class PiLinkMonitor:
    """Continuously track Aux -> Pi control-plane reachability.

    The old implementation sampled the Pi exactly once during Aux startup.  If
    the Pi API started a moment later, the published component status remained
    OFFLINE forever.  This monitor uses the lightweight /v1/health endpoint and
    only publishes when the link changes state.
    """

    def __init__(
        self,
        client: PiClient,
        on_status: Callable[[str, str | None], None],
        *,
        period_s: float = 2.0,
    ) -> None:
        self.client = client
        self.on_status = on_status
        self.period_s = max(0.5, float(period_s))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_status: str | None = None

    def probe_once(self) -> str:
        detail: str | None = None
        try:
            self.client.health()
            status = "online"
        except Exception as exc:
            status = "offline"
            detail = str(exc)

        if status != self._last_status:
            self._last_status = status
            self.on_status(status, detail)
        return status

    def _run(self) -> None:
        self.probe_once()
        while not self._stop.wait(self.period_s):
            self.probe_once()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="pi-link-monitor")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.period_s + 0.5))
            self._thread = None
