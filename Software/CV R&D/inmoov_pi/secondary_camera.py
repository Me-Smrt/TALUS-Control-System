from __future__ import annotations

import sys
import threading
import time
from typing import Any

import cv2

from .frame_store import LatestFrameStore
from .state import RobotStateHub


class SecondaryCameraWorker:
    """Own a non-tracking USB camera in a background capture thread."""

    def __init__(self, config: dict[str, Any], frames: LatestFrameStore, state: RobotStateHub) -> None:
        self.config = dict(config)
        self.frames = frames
        self.state = state
        self.camera_id = str(self.config["id"])
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name=f"camera-{self.camera_id}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _open(self):
        index = int(self.config.get("index", 1))
        if sys.platform == "win32" and hasattr(cv2, "CAP_DSHOW"):
            cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        else:
            cap = cv2.VideoCapture(index)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(self.config.get("width", 640)))
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(self.config.get("height", 480)))
        cap.set(cv2.CAP_PROP_FPS, int(self.config.get("fps", 30)))
        return cap

    def _run(self) -> None:
        label = str(self.config.get("label", self.camera_id))
        reconnect_s = max(0.25, float(self.config.get("reconnect_s", 2.0)))
        sequence = 0
        while not self._stop.is_set():
            cap = self._open()
            if not cap.isOpened():
                self.state.update_camera(self.camera_id, label=label, enabled=True, status="offline",
                                         error="could_not_open", processed_available=False)
                cap.release()
                self._stop.wait(reconnect_s)
                continue
            self.state.update_camera(self.camera_id, label=label, enabled=True, status="online",
                                     error=None, processed_available=False,
                                     role=str(self.config.get("role", "secondary")))
            try:
                while not self._stop.is_set():
                    ok, frame = cap.read()
                    if not ok:
                        self.state.update_camera(self.camera_id, status="offline", error="read_failed")
                        break
                    sequence += 1
                    mono = time.monotonic_ns()
                    unix = time.time_ns()
                    meta = self.frames.publish_raw(self.camera_id, frame, sequence=sequence,
                                                   monotonic_ns=mono, unix_ns=unix)
                    self.state.update_camera(
                        self.camera_id,
                        status="online",
                        sequence=meta.sequence,
                        width=meta.width,
                        height=meta.height,
                        captured_monotonic_ns=meta.captured_monotonic_ns,
                        captured_unix_ns=meta.captured_unix_ns,
                        processed_available=False,
                    )
            finally:
                cap.release()
            self._stop.wait(reconnect_s)
