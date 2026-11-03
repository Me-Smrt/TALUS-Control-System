from __future__ import annotations

import io
import json
import math
import time
import zipfile
from typing import Any

import cv2
import numpy as np

from .frame_store import FrameMetadata, LatestFrameStore
from .state import RobotStateHub


_BODY_POINTS = {
    "nose": 0,
    "left_shoulder": 11,
    "right_shoulder": 12,
    "left_elbow": 13,
    "right_elbow": 14,
    "left_wrist": 15,
    "right_wrist": 16,
    "left_hip": 23,
    "right_hip": 24,
    "left_knee": 25,
    "right_knee": 26,
    "left_ankle": 27,
    "right_ankle": 28,
}


def _point(points: Any, idx: int) -> list[float] | None:
    try:
        value = points[idx]
        if len(value) < 3:
            return None
        return [round(float(value[0]), 6), round(float(value[1]), 6), round(float(value[2]), 6)]
    except (TypeError, ValueError, IndexError, KeyError):
        return None


def compact_perception(detail: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(detail, dict):
        return {}
    p = detail.get("perception", {}) if isinstance(detail.get("perception"), dict) else {}
    body = p.get("body", {}) if isinstance(p.get("body"), dict) else {}
    face = p.get("face", {}) if isinstance(p.get("face"), dict) else {}
    hands = p.get("hands", {}) if isinstance(p.get("hands"), dict) else {}
    norm = body.get("normalized_landmarks", [])
    world = body.get("world_landmarks_m", [])
    vis = body.get("visibility", [])

    keypoints: dict[str, Any] = {}
    if bool(body.get("valid")):
        for name, idx in _BODY_POINTS.items():
            n = _point(norm, idx)
            w = _point(world, idx)
            try:
                visibility = round(float(vis[idx]), 4)
            except (TypeError, ValueError, IndexError):
                visibility = None
            keypoints[name] = {
                "image_normalized": n,
                "mediapipe_world_m": w,
                "visibility": visibility,
            }

    return {
        "captured_monotonic_ns": detail.get("captured_monotonic_ns"),
        "captured_unix_ns": detail.get("captured_unix_ns"),
        "frame_sequence": detail.get("frame_sequence"),
        "body": {
            "valid": bool(body.get("valid")),
            "keypoints": keypoints,
            "joint_metrics_rad": body.get("joint_metrics_rad", {}) if bool(body.get("valid")) else {},
        },
        "face": {
            "valid": bool(face.get("valid")),
            "head_pose_rad": face.get("head_pose_rad", {}) if bool(face.get("valid")) else {},
        },
        "hands": {
            side: {
                "valid": bool((hands.get(side) or {}).get("valid")),
                "curls": (hands.get(side) or {}).get("curls", {}) if bool((hands.get(side) or {}).get("valid")) else {},
            }
            for side in ("left", "right")
        },
    }


def _encode_jpeg(frame: np.ndarray, *, quality: int, max_width: int | None) -> bytes:
    img = frame
    if max_width and img.shape[1] > max_width:
        scale = float(max_width) / float(img.shape[1])
        h = max(1, int(round(img.shape[0] * scale)))
        img = cv2.resize(img, (int(max_width), h), interpolation=cv2.INTER_AREA)
    ok, encoded = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    if not ok:
        raise RuntimeError("OpenCV failed to encode temporal observation frame")
    return encoded.tobytes()


def capture_temporal_observation(
    frames: LatestFrameStore,
    state: RobotStateHub,
    *,
    camera_id: str,
    view: str = "raw",
    duration_ms: int = 1600,
    samples: int = 5,
    jpeg_quality: int = 82,
    max_width: int | None = 640,
) -> tuple[bytes, dict[str, Any]]:
    """Capture an on-demand, bounded chronological observation.

    No continuous video stream leaves the Pi.  The API request samples the
    Pi-owned camera at a small fixed number of points, bundles JPEGs + compact
    pose metadata, and then ends.
    """

    samples = max(1, int(samples))
    duration_ms = max(0, int(duration_ms))
    duration_s = duration_ms / 1000.0
    interval = 0.0 if samples <= 1 else duration_s / float(samples - 1)
    started = time.monotonic()
    captured: list[tuple[bytes, FrameMetadata, dict[str, Any], float]] = []
    last_sequence = -1

    for index in range(samples):
        target = started + interval * index
        delay = target - time.monotonic()
        if delay > 0:
            time.sleep(delay)

        if index == 0:
            item = frames.get_image(camera_id, view, allow_raw_fallback=True)
        else:
            item = frames.wait_for_newer(
                camera_id,
                view,
                after_sequence=last_sequence,
                timeout_s=max(0.35, interval + 0.35),
                allow_raw_fallback=True,
            )
        if item is None:
            continue
        image, meta = item
        if meta.sequence <= last_sequence:
            continue
        last_sequence = meta.sequence

        perception = state.wait_for_perception_at_or_after(meta.captured_monotonic_ns, timeout_s=0.20)
        compact = compact_perception(perception)
        relative_ms = (time.monotonic() - started) * 1000.0
        captured.append((_encode_jpeg(image, quality=jpeg_quality, max_width=max_width), meta, compact, relative_ms))

    if not captured:
        raise RuntimeError("no camera frames were available during the observation window")

    actual_duration_ms = max(0.0, captured[-1][3] - captured[0][3]) if len(captured) > 1 else 0.0
    manifest: dict[str, Any] = {
        "schema": "automaton.temporal_observation.v1",
        "camera_id": str(camera_id),
        "view": str(view),
        "requested_duration_ms": duration_ms,
        "actual_duration_ms": round(actual_duration_ms, 2),
        "samples_requested": samples,
        "samples_captured": len(captured),
        "chronological": True,
        "depth": {
            "available": False,
            "note": "Depth transport is reserved for the RGB-D integration pass; MediaPipe world landmarks are not camera depth.",
        },
        "frames": [],
    }

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=4) as zf:
        for i, (jpeg, meta, compact, relative_ms) in enumerate(captured):
            name = f"frame_{i:02d}.jpg"
            zf.writestr(name, jpeg)
            manifest["frames"].append({
                "index": i,
                "file": name,
                "relative_ms": round(relative_ms - captured[0][3], 2),
                "sequence": meta.sequence,
                "captured_monotonic_ns": meta.captured_monotonic_ns,
                "captured_unix_ns": meta.captured_unix_ns,
                "width": meta.width,
                "height": meta.height,
                "fallback_from": meta.fallback_from,
                "perception": compact,
            })
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, separators=(",", ":")))
    return out.getvalue(), manifest
