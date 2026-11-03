from __future__ import annotations

import math
from typing import Any

import cv2
import numpy as np


def build_contact_sheet(
    jpeg_frames: list[bytes],
    manifest: dict[str, Any],
    *,
    tile_width: int = 360,
    max_columns: int = 3,
    jpeg_quality: int = 88,
) -> bytes:
    """Build one chronological image containing all sampled observation frames.

    llama.cpp/Qwen currently receives one image in the TALUS client. A contact
    sheet keeps the existing model API while still exposing temporal evidence.
    """
    decoded: list[np.ndarray] = []
    labels: list[str] = []
    meta_frames = manifest.get("frames", []) if isinstance(manifest, dict) else []
    for i, data in enumerate(jpeg_frames):
        img = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            continue
        scale = min(1.0, float(tile_width) / max(1.0, float(img.shape[1])))
        width = max(1, int(round(img.shape[1] * scale)))
        height = max(1, int(round(img.shape[0] * scale)))
        if scale != 1.0:
            img = cv2.resize(img, (width, height), interpolation=cv2.INTER_AREA)
        rel = None
        if i < len(meta_frames) and isinstance(meta_frames[i], dict):
            rel = meta_frames[i].get("relative_ms")
        label = f"Frame {i + 1}"
        try:
            label += f"  t={float(rel) / 1000.0:.2f}s"
        except (TypeError, ValueError):
            pass
        decoded.append(img)
        labels.append(label)

    if not decoded:
        raise ValueError("Temporal observation did not contain decodable JPEG frames")

    tile_h = max(img.shape[0] for img in decoded) + 34
    tile_w = max(img.shape[1] for img in decoded)
    cols = min(max(1, int(max_columns)), len(decoded))
    rows = int(math.ceil(len(decoded) / cols))
    canvas = np.zeros((rows * tile_h, cols * tile_w, 3), dtype=np.uint8)

    for i, (img, label) in enumerate(zip(decoded, labels)):
        row, col = divmod(i, cols)
        y0 = row * tile_h
        x0 = col * tile_w
        h, w = img.shape[:2]
        canvas[y0 + 34:y0 + 34 + h, x0:x0 + w] = img
        cv2.putText(
            canvas,
            label,
            (x0 + 7, y0 + 23),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )

    ok, encoded = cv2.imencode(".jpg", canvas, [int(cv2.IMWRITE_JPEG_QUALITY), int(jpeg_quality)])
    if not ok:
        raise RuntimeError("Could not encode temporal contact sheet")
    return encoded.tobytes()


def _point(frame: dict[str, Any], name: str) -> tuple[float, float] | None:
    try:
        value = frame["perception"]["body"]["keypoints"][name]["image_normalized"]
        if value is None or len(value) < 2:
            return None
        return float(value[0]), float(value[1])
    except (TypeError, ValueError, KeyError, IndexError):
        return None


def _direction_reversals(values: list[float], epsilon: float = 0.012) -> int:
    """Count meaningful direction changes while ignoring landmark jitter."""
    signs: list[int] = []
    for a, b in zip(values, values[1:]):
        delta = b - a
        if abs(delta) < epsilon:
            continue
        signs.append(1 if delta > 0 else -1)
    return sum(1 for a, b in zip(signs, signs[1:]) if a != b)


def _trajectory_summary(frames: list[dict[str, Any]], name: str) -> dict[str, float | int | str] | None:
    points = [p for p in (_point(f, name) for f in frames) if p is not None]
    if len(points) < 2:
        return None
    dx = points[-1][0] - points[0][0]
    dy = points[-1][1] - points[0][1]
    path = 0.0
    horizontal_path = 0.0
    vertical_path = 0.0
    for a, b in zip(points, points[1:]):
        sx = b[0] - a[0]
        sy = b[1] - a[1]
        path += math.hypot(sx, sy)
        horizontal_path += abs(sx)
        vertical_path += abs(sy)
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    dominant_axis = "horizontal" if horizontal_path > vertical_path * 1.25 else "vertical" if vertical_path > horizontal_path * 1.25 else "mixed"
    return {
        "dx": round(dx, 4),
        "dy": round(dy, 4),
        "path": round(path, 4),
        "horizontal_path": round(horizontal_path, 4),
        "vertical_path": round(vertical_path, 4),
        "x_range": round(max(xs) - min(xs), 4),
        "y_range": round(max(ys) - min(ys), 4),
        "horizontal_reversals": _direction_reversals(xs),
        "vertical_reversals": _direction_reversals(ys),
        "dominant_axis": dominant_axis,
    }


def _wrist_raised_fraction(frames: list[dict[str, Any]], side: str) -> float | None:
    vals: list[bool] = []
    for frame in frames:
        wrist = _point(frame, f"{side}_wrist")
        shoulder = _point(frame, f"{side}_shoulder")
        if wrist is None or shoulder is None:
            continue
        # Normalized image y increases downward.  A small margin avoids
        # classifying shoulder-level jitter as a deliberately raised hand.
        vals.append(wrist[1] < shoulder[1] - 0.025)
    if not vals:
        return None
    return sum(1 for v in vals if v) / len(vals)


def summarize_motion(manifest: dict[str, Any]) -> str:
    frames = manifest.get("frames", []) if isinstance(manifest, dict) else []
    if not isinstance(frames, list) or not frames:
        return "No synchronized pose metadata was available for the sampled frames."

    lines = [
        "Chronological temporal observation. Image coordinates are normalized: +x is screen-right and +y is downward.",
        f"Captured {len(frames)} samples across approximately {float(manifest.get('actual_duration_ms', 0.0)) / 1000.0:.2f} s.",
    ]
    max_path = 0.0
    for name in ("nose", "left_shoulder", "right_shoulder", "left_wrist", "right_wrist", "left_hip", "right_hip"):
        summary = _trajectory_summary(frames, name)
        if summary is None:
            continue
        max_path = max(max_path, summary["path"])
        extra = ""
        if name in {"left_wrist", "right_wrist"}:
            side = name.split("_", 1)[0]
            raised = _wrist_raised_fraction(frames, side)
            raised_text = f", raised={raised:.0%}" if raised is not None else ""
            repeated_lateral = (
                int(summary.get("horizontal_reversals", 0)) >= 1
                and float(summary.get("horizontal_path", 0.0)) >= 0.08
                and summary.get("dominant_axis") == "horizontal"
            )
            extra = (
                f", x-reversals={int(summary.get('horizontal_reversals', 0))}, "
                f"y-reversals={int(summary.get('vertical_reversals', 0))}, "
                f"dominant={summary.get('dominant_axis')}"
                f"{raised_text}, repeated-lateral={'yes' if repeated_lateral else 'no'}"
            )
        lines.append(
            f"{name}: dx={summary['dx']:+.3f}, dy={summary['dy']:+.3f}, "
            f"path={summary['path']:.3f}, x-range={summary['x_range']:.3f}, y-range={summary['y_range']:.3f}{extra}."
        )

    yaws: list[float] = []
    for frame in frames:
        try:
            yaw = frame["perception"]["face"]["head_pose_rad"].get("yaw")
            if yaw is not None:
                yaws.append(float(yaw))
        except (TypeError, ValueError, KeyError):
            pass
    if len(yaws) >= 2:
        lines.append(f"head yaw range={max(yaws) - min(yaws):.3f} rad.")

    lines.append(
        "Pose motion is a deterministic cue, not an activity label. Wrist direction reversals and raised-hand fractions are provided to help distinguish gestures such as waving from a static raised hand. Use them together with the chronological images, and do not describe motion that the sampled frames do not support."
    )
    if not bool((manifest.get("depth") or {}).get("available", False)):
        lines.append("Camera depth is not available in this observation; MediaPipe world landmarks must not be treated as RGB-D depth.")
    return "\n".join(lines)
