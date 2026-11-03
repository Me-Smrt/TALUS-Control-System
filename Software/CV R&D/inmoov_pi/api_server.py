from __future__ import annotations

import json
import os
import secrets
import threading
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .behavior import BehaviorBroker
from .frame_store import LatestFrameStore
from .state import RobotStateHub
from .temporal_observation import capture_temporal_observation


class ControlApiServer:
    """Pi control-plane HTTP API.

    Camera/state operations remain observation-only.  The optional behavior
    endpoint accepts *semantic* intents only and never exposes PWM/CAN/joint
    writes.  In R&D it defaults to planning-only, so requests can be exercised
    end-to-end without actuating hardware.
    """

    def __init__(
        self,
        config: dict[str, Any],
        state: RobotStateHub,
        frames: LatestFrameStore,
        *,
        behaviors: BehaviorBroker | None = None,
        observation_config: dict[str, Any] | None = None,
    ) -> None:
        self.config = dict(config)
        self.state = state
        self.frames = frames
        self.behaviors = behaviors
        self.observation_config = dict(observation_config or {})
        self.host = str(self.config.get("bind_host", "127.0.0.1"))
        self.port = int(self.config.get("port", 8766))
        self.jpeg_quality = int(self.config.get("jpeg_quality", 85))
        token_env = str(self.config.get("token_env", "AUTOMATON_API_TOKEN"))
        self.token = os.getenv(token_env, "").strip()
        self.allow_loopback_without_token = bool(self.config.get("allow_unauthenticated_loopback", True))
        if self.host not in {"127.0.0.1", "localhost", "::1"} and not self.token:
            raise RuntimeError(
                f"Refusing to bind control API to {self.host} without {token_env}. "
                "Set a bearer token before exposing the service to the LAN."
            )
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._server is not None:
            return
        outer = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "AutomatonPiAPI/0.4"

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
                if bool(outer.config.get("access_log", False)):
                    super().log_message(format, *args)

            def _authorized(self) -> bool:
                if outer.token:
                    header = self.headers.get("Authorization", "")
                    prefix = "Bearer "
                    supplied = header[len(prefix):] if header.startswith(prefix) else ""
                    return bool(supplied and secrets.compare_digest(supplied, outer.token))
                return outer.allow_loopback_without_token and self.client_address[0] in {"127.0.0.1", "::1"}

            def _json(self, status: int, payload: Any) -> None:
                data = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(data)

            def _read_json(self, *, max_bytes: int = 32 * 1024) -> dict[str, Any]:
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError as exc:
                    raise ValueError("invalid_content_length") from exc
                if length <= 0 or length > max_bytes:
                    raise ValueError("invalid_body_size")
                raw = self.rfile.read(length)
                payload = json.loads(raw.decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("json_body_must_be_object")
                return payload

            @staticmethod
            def _valid_camera_id(camera_id: str) -> bool:
                return bool(camera_id) and not any(
                    ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
                    for ch in camera_id
                )

            def _observation_params(self, query: dict[str, list[str]]) -> tuple[str, int, int, int, int]:
                cfg = outer.observation_config
                if not bool(cfg.get("enabled", True)):
                    raise RuntimeError("temporal_observation_disabled")
                view = query.get("view", ["raw"])[0]
                if view not in {"raw", "processed"}:
                    raise ValueError("invalid_view")
                try:
                    duration_ms = int(query.get("duration_ms", [str(cfg.get("default_duration_ms", 1600))])[0])
                    samples = int(query.get("samples", [str(cfg.get("default_samples", 5))])[0])
                    max_width = int(query.get("max_width", [str(cfg.get("max_width", 640))])[0])
                except (TypeError, ValueError) as exc:
                    raise ValueError("invalid_observation_parameters") from exc
                max_duration = max(0, int(cfg.get("max_duration_ms", 4000)))
                max_samples = max(1, int(cfg.get("max_samples", 8)))
                if duration_ms < 0 or duration_ms > max_duration:
                    raise ValueError("duration_ms_out_of_range")
                if samples < 1 or samples > max_samples:
                    raise ValueError("samples_out_of_range")
                max_width = max(160, min(1920, max_width))
                quality = max(40, min(95, int(cfg.get("jpeg_quality", 82))))
                return view, duration_ms, samples, max_width, quality

            def do_GET(self) -> None:  # noqa: N802
                if not self._authorized():
                    self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                    return
                parsed = urllib.parse.urlsplit(self.path)
                path = parsed.path.rstrip("/") or "/"
                query = urllib.parse.parse_qs(parsed.query)

                if path == "/v1/health":
                    snap = outer.state.snapshot()
                    self._json(HTTPStatus.OK, {
                        "status": snap["system"]["status"],
                        "schema": snap["schema"],
                        "version": snap["service_version"],
                        "uptime_s": snap["system"]["uptime_s"],
                    })
                    return
                if path == "/v1/state":
                    self._json(HTTPStatus.OK, outer.state.snapshot())
                    return
                if path == "/v1/world":
                    self._json(HTTPStatus.OK, outer.state.world_snapshot())
                    return
                if path == "/v1/perception":
                    self._json(HTTPStatus.OK, outer.state.perception_detail())
                    return
                if path == "/v1/cameras":
                    snap = outer.state.snapshot()
                    self._json(HTTPStatus.OK, {
                        "cameras": snap.get("cameras", {}),
                        "frames": outer.frames.metadata(),
                    })
                    return
                if path == "/v1/behaviors":
                    if outer.behaviors is None:
                        self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "behavior_broker_unavailable"})
                    else:
                        self._json(HTTPStatus.OK, outer.behaviors.snapshot())
                    return
                if path == "/v1/contract":
                    behavior_enabled = outer.behaviors is not None
                    self._json(HTTPStatus.OK, {
                        "schema": "automaton.pi_api.v1",
                        "read_only": not behavior_enabled,
                        "direct_actuator_control": False,
                        "behavior_submission": "high_level_semantic_only" if behavior_enabled else "disabled",
                        "endpoints": [
                            "GET /v1/health",
                            "GET /v1/state",
                            "GET /v1/perception",
                            "GET /v1/world",
                            "GET /v1/cameras",
                            "GET /v1/cameras/{camera_id}/frame?view=raw|processed&max_age_ms=N",
                            "GET /v1/cameras/{camera_id}/observe?view=raw|processed&duration_ms=N&samples=N",
                            "GET /v1/behaviors",
                            "GET /v1/behaviors/{request_id}",
                            "POST /v1/behaviors",
                            "POST /v1/behaviors/{request_id}/cancel",
                        ] if behavior_enabled else [
                            "GET /v1/health",
                            "GET /v1/state",
                            "GET /v1/perception",
                            "GET /v1/world",
                            "GET /v1/cameras",
                            "GET /v1/cameras/{camera_id}/frame?view=raw|processed&max_age_ms=N",
                            "GET /v1/cameras/{camera_id}/observe?view=raw|processed&duration_ms=N&samples=N",
                        ],
                        "camera_delivery": "bounded_on_demand_snapshot_or_temporal_observation",
                        "continuous_raw_video_stream": False,
                    })
                    return

                parts = [p for p in path.split("/") if p]
                if len(parts) == 3 and parts[:2] == ["v1", "behaviors"]:
                    if outer.behaviors is None:
                        self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "behavior_broker_unavailable"})
                        return
                    request_id = urllib.parse.unquote(parts[2])
                    item = outer.behaviors.get(request_id)
                    if item is None:
                        self._json(HTTPStatus.NOT_FOUND, {"error": "behavior_not_found"})
                    else:
                        self._json(HTTPStatus.OK, item)
                    return

                if len(parts) == 4 and parts[:2] == ["v1", "cameras"] and parts[3] == "frame":
                    camera_id = urllib.parse.unquote(parts[2])
                    if not self._valid_camera_id(camera_id):
                        self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_camera_id"})
                        return
                    view = query.get("view", ["processed"])[0]
                    if view not in {"raw", "processed"}:
                        self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_view"})
                        return
                    item = outer.frames.get_jpeg(camera_id, view, quality=outer.jpeg_quality, allow_raw_fallback=True)
                    if item is None:
                        self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "frame_unavailable", "camera_id": camera_id, "view": view})
                        return
                    data, meta = item
                    max_age_ms = None
                    try:
                        if "max_age_ms" in query:
                            max_age_ms = max(0.0, float(query["max_age_ms"][0]))
                    except (TypeError, ValueError):
                        self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_max_age_ms"})
                        return
                    age_ms = meta.age_ms()
                    if max_age_ms is not None and age_ms > max_age_ms:
                        self._json(HTTPStatus.CONFLICT, {
                            "error": "frame_too_old",
                            "camera_id": camera_id,
                            "view": view,
                            "age_ms": age_ms,
                            "max_age_ms": max_age_ms,
                        })
                        return
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Cache-Control", "no-store, max-age=0")
                    self.send_header("X-Automaton-Camera", camera_id)
                    self.send_header("X-Automaton-View", meta.view)
                    self.send_header("X-Automaton-Frame-Sequence", str(meta.sequence))
                    self.send_header("X-Automaton-Frame-Age-Ms", f"{age_ms:.3f}")
                    self.send_header("X-Automaton-Frame-Monotonic-Ns", str(meta.captured_monotonic_ns))
                    self.send_header("X-Automaton-Frame-Unix-Ns", str(meta.captured_unix_ns))
                    if meta.fallback_from:
                        self.send_header("X-Automaton-Fallback-From", meta.fallback_from)
                    self.end_headers()
                    self.wfile.write(data)
                    return

                if len(parts) == 4 and parts[:2] == ["v1", "cameras"] and parts[3] == "observe":
                    camera_id = urllib.parse.unquote(parts[2])
                    if not self._valid_camera_id(camera_id):
                        self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_camera_id"})
                        return
                    try:
                        view, duration_ms, samples, max_width, quality = self._observation_params(query)
                        data, manifest = capture_temporal_observation(
                            outer.frames,
                            outer.state,
                            camera_id=camera_id,
                            view=view,
                            duration_ms=duration_ms,
                            samples=samples,
                            jpeg_quality=quality,
                            max_width=max_width,
                        )
                    except ValueError as exc:
                        self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                        return
                    except RuntimeError as exc:
                        self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(exc)})
                        return
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "application/zip")
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("X-Automaton-Observation-Schema", str(manifest.get("schema")))
                    self.send_header("X-Automaton-Observation-Samples", str(manifest.get("samples_captured")))
                    self.send_header("X-Automaton-Observation-Duration-Ms", str(manifest.get("actual_duration_ms")))
                    self.end_headers()
                    self.wfile.write(data)
                    return

                self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

            def do_POST(self) -> None:  # noqa: N802
                if not self._authorized():
                    self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                    return
                parsed = urllib.parse.urlsplit(self.path)
                path = parsed.path.rstrip("/") or "/"
                parts = [p for p in path.split("/") if p]

                if path == "/v1/behaviors":
                    if outer.behaviors is None:
                        self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "behavior_broker_unavailable"})
                        return
                    try:
                        payload = self._read_json()
                        result = outer.behaviors.submit(payload)
                    except (ValueError, TypeError) as exc:
                        self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                        return
                    self._json(HTTPStatus.ACCEPTED, result)
                    return

                if len(parts) == 4 and parts[:2] == ["v1", "behaviors"] and parts[3] == "cancel":
                    if outer.behaviors is None:
                        self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "behavior_broker_unavailable"})
                        return
                    request_id = urllib.parse.unquote(parts[2])
                    result = outer.behaviors.cancel(request_id)
                    if result is None:
                        self._json(HTTPStatus.NOT_FOUND, {"error": "behavior_not_found"})
                    else:
                        self._json(HTTPStatus.OK, result)
                    return

                self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

        self._server = ThreadingHTTPServer((self.host, self.port), Handler)
        self.port = int(self._server.server_address[1])
        self._thread = threading.Thread(target=self._server.serve_forever, name="automaton-control-api", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def __enter__(self) -> "ControlApiServer":
        self.start()
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.stop()
