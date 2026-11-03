from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np


@dataclass(frozen=True)
class FrameMetadata:
    camera_id: str
    view: str
    sequence: int
    captured_monotonic_ns: int
    captured_unix_ns: int
    width: int
    height: int
    fallback_from: str | None = None

    def age_ms(self, now_ns: int | None = None) -> float:
        now_ns = time.monotonic_ns() if now_ns is None else int(now_ns)
        return max(0.0, (now_ns - self.captured_monotonic_ns) / 1_000_000.0)

    def as_dict(self) -> dict[str, Any]:
        return {
            "camera_id": self.camera_id,
            "view": self.view,
            "sequence": self.sequence,
            "captured_monotonic_ns": self.captured_monotonic_ns,
            "captured_unix_ns": self.captured_unix_ns,
            "width": self.width,
            "height": self.height,
            "fallback_from": self.fallback_from,
            "age_ms": self.age_ms(),
        }


@dataclass
class _StoredFrame:
    frame: np.ndarray
    meta: FrameMetadata
    jpeg_cache_quality: int | None = None
    jpeg_cache: bytes | None = None


class LatestFrameStore:
    """Thread-safe latest-frame broker.

    Frames stay in Pi memory. JPEG encoding is lazy and happens only when a
    dashboard or auxiliary client actually requests a snapshot, so owning the
    cameras does not imply continuously streaming image data over the network.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._frames: dict[tuple[str, str], _StoredFrame] = {}
        self._sequences: dict[str, int] = {}

    def _publish(self, camera_id: str, view: str, frame: np.ndarray, *, sequence: int | None = None,
                 monotonic_ns: int | None = None, unix_ns: int | None = None) -> FrameMetadata:
        if frame is None or not isinstance(frame, np.ndarray) or frame.ndim < 2:
            raise ValueError("frame must be a valid NumPy image")
        camera_id = str(camera_id)
        view = str(view)
        now_mono = time.monotonic_ns() if monotonic_ns is None else int(monotonic_ns)
        now_unix = time.time_ns() if unix_ns is None else int(unix_ns)
        with self._lock:
            if sequence is None:
                sequence = self._sequences.get(camera_id, 0) + 1
            self._sequences[camera_id] = max(self._sequences.get(camera_id, 0), int(sequence))
            h, w = frame.shape[:2]
            meta = FrameMetadata(camera_id, view, int(sequence), now_mono, now_unix, int(w), int(h))
            self._frames[(camera_id, view)] = _StoredFrame(frame.copy(), meta)
            self._condition.notify_all()
            return meta

    def publish_raw(self, camera_id: str, frame: np.ndarray, **kwargs: Any) -> FrameMetadata:
        return self._publish(camera_id, "raw", frame, **kwargs)

    def publish_processed(self, camera_id: str, frame: np.ndarray, **kwargs: Any) -> FrameMetadata:
        return self._publish(camera_id, "processed", frame, **kwargs)

    def get_image(self, camera_id: str, view: str = "processed", *, allow_raw_fallback: bool = True) -> tuple[np.ndarray, FrameMetadata] | None:
        key = (str(camera_id), str(view))
        with self._lock:
            stored = self._frames.get(key)
            if stored is not None:
                return stored.frame.copy(), stored.meta
            if view == "processed" and allow_raw_fallback:
                raw = self._frames.get((str(camera_id), "raw"))
                if raw is not None:
                    m = raw.meta
                    meta = FrameMetadata(m.camera_id, "processed", m.sequence, m.captured_monotonic_ns,
                                         m.captured_unix_ns, m.width, m.height, fallback_from="raw")
                    return raw.frame.copy(), meta
        return None

    def get_jpeg(self, camera_id: str, view: str = "processed", *, quality: int = 85,
                 allow_raw_fallback: bool = True) -> tuple[bytes, FrameMetadata] | None:
        quality = max(30, min(100, int(quality)))
        key = (str(camera_id), str(view))
        with self._lock:
            stored = self._frames.get(key)
            fallback = False
            if stored is None and view == "processed" and allow_raw_fallback:
                stored = self._frames.get((str(camera_id), "raw"))
                fallback = stored is not None
            if stored is None:
                return None
            if not fallback and stored.jpeg_cache is not None and stored.jpeg_cache_quality == quality:
                return stored.jpeg_cache, stored.meta
            frame = stored.frame.copy()
            source_meta = stored.meta

        ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
        if not ok:
            raise RuntimeError("OpenCV failed to encode camera frame as JPEG")
        data = encoded.tobytes()

        if fallback:
            meta = FrameMetadata(source_meta.camera_id, "processed", source_meta.sequence,
                                 source_meta.captured_monotonic_ns, source_meta.captured_unix_ns,
                                 source_meta.width, source_meta.height, fallback_from="raw")
        else:
            meta = source_meta
            with self._lock:
                current = self._frames.get(key)
                if current is stored:
                    current.jpeg_cache = data
                    current.jpeg_cache_quality = quality
        return data, meta


    def wait_for_newer(
        self,
        camera_id: str,
        view: str = "processed",
        *,
        after_sequence: int,
        timeout_s: float = 1.0,
        allow_raw_fallback: bool = True,
    ) -> tuple[np.ndarray, FrameMetadata] | None:
        """Wait for a newer frame without polling the camera from another process."""
        deadline = time.monotonic() + max(0.0, float(timeout_s))
        key = (str(camera_id), str(view))
        with self._condition:
            while True:
                stored = self._frames.get(key)
                fallback = False
                if stored is None and view == "processed" and allow_raw_fallback:
                    stored = self._frames.get((str(camera_id), "raw"))
                    fallback = stored is not None
                if stored is not None and stored.meta.sequence > int(after_sequence):
                    meta = stored.meta
                    if fallback:
                        meta = FrameMetadata(
                            meta.camera_id, "processed", meta.sequence, meta.captured_monotonic_ns,
                            meta.captured_unix_ns, meta.width, meta.height, fallback_from="raw"
                        )
                    return stored.frame.copy(), meta
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(remaining)

    def camera_ids(self) -> list[str]:
        with self._lock:
            return sorted({camera_id for camera_id, _view in self._frames})

    def metadata(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        with self._lock:
            items = list(self._frames.items())
        for (camera_id, view), stored in items:
            result.setdefault(camera_id, {})[view] = stored.meta.as_dict()
        return result
