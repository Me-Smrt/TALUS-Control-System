from __future__ import annotations

import urllib.request
from pathlib import Path
from typing import Any

import cv2
import numpy as np


class HolisticTracker:
    """Thin wrapper around the current MediaPipe Holistic Landmarker task API."""

    def __init__(self, config: dict[str, Any], project_root: Path) -> None:
        self.config = config
        self.project_root = Path(project_root)
        model_path = Path(config["model_path"])
        if not model_path.is_absolute():
            model_path = self.project_root / model_path
        self.model_path = model_path
        self._ensure_model()

        try:
            from mediapipe.tasks.python.core import base_options as base_options_module
            from mediapipe.tasks.python.vision import holistic_landmarker
            from mediapipe.tasks.python.vision.core import image as image_lib
            from mediapipe.tasks.python.vision.core import vision_task_running_mode as running_mode_module
        except Exception as exc:  # pragma: no cover - depends on local install
            raise RuntimeError(
                "MediaPipe Tasks could not be imported. Install requirements.txt in a fresh virtual environment."
            ) from exc

        self._image_lib = image_lib
        options = holistic_landmarker.HolisticLandmarkerOptions(
            base_options=base_options_module.BaseOptions(model_asset_path=str(self.model_path)),
            running_mode=running_mode_module.VisionTaskRunningMode.VIDEO,
            min_face_detection_confidence=float(config.get("min_face_detection_confidence", 0.5)),
            min_face_landmarks_confidence=float(config.get("min_face_landmarks_confidence", 0.5)),
            min_pose_detection_confidence=float(config.get("min_pose_detection_confidence", 0.5)),
            min_pose_landmarks_confidence=float(config.get("min_pose_landmarks_confidence", 0.5)),
            min_hand_landmarks_confidence=float(config.get("min_hand_landmarks_confidence", 0.5)),
            output_face_blendshapes=bool(config.get("output_face_blendshapes", True)),
            output_segmentation_mask=False,
        )
        self.landmarker = holistic_landmarker.HolisticLandmarker.create_from_options(options)

    def _ensure_model(self) -> None:
        if self.model_path.exists() and self.model_path.stat().st_size > 1024:
            return
        url = str(self.config.get("model_url", "")).strip()
        if not url:
            raise FileNotFoundError(f"Holistic model not found: {self.model_path}")
        self.model_path.parent.mkdir(parents=True, exist_ok=True)
        print(f"[CV] Downloading MediaPipe Holistic model to {self.model_path}")
        request = urllib.request.Request(url, headers={"User-Agent": "InMoov-CV-POC/0.1"})
        with urllib.request.urlopen(request, timeout=120) as response, self.model_path.open("wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
        if self.model_path.stat().st_size <= 1024:
            raise RuntimeError("Downloaded MediaPipe model is unexpectedly small")

    def detect(self, frame_bgr: np.ndarray, timestamp_ms: int):
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        rgb = np.ascontiguousarray(rgb)
        mp_image = self._image_lib.Image(
            image_format=self._image_lib.ImageFormat.SRGB,
            data=rgb,
        )
        return self.landmarker.detect_for_video(mp_image, int(timestamp_ms))

    def close(self) -> None:
        close = getattr(self.landmarker, "close", None)
        if callable(close):
            close()

    def __enter__(self) -> "HolisticTracker":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
