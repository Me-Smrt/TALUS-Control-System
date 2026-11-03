from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import numpy as np


class FaceIdentityError(RuntimeError):
    pass


class SFaceIdentityBackend:
    """Local OpenCV YuNet + SFace embedding backend.

    The Pi remains the owner of cameras.  This backend only receives an on-demand
    JPEG snapshot from PiClient when the session manager needs to identify or
    enroll the currently visible face.
    """

    def __init__(self, cfg: dict[str, Any], root: Path) -> None:
        self.cfg = dict(cfg or {})
        self.root = Path(root)
        self.enabled = bool(self.cfg.get("enabled", True))
        self.detector_path = self._resolve(self.cfg.get("detector_model_path", "models/face/face_detection_yunet_2023mar.onnx"))
        self.recognizer_path = self._resolve(self.cfg.get("recognition_model_path", "models/face/face_recognition_sface_2021dec.onnx"))
        self.detector_score = float(self.cfg.get("detector_score_threshold", 0.85))
        self.detector_nms = float(self.cfg.get("detector_nms_threshold", 0.3))
        self.detector_top_k = int(self.cfg.get("detector_top_k", 5000))
        self._detector = None
        self._recognizer = None

    def _resolve(self, value: str | Path) -> Path:
        p = Path(value)
        return p if p.is_absolute() else (self.root / p).resolve()

    def available(self) -> bool:
        if not self.enabled:
            return False
        if not (self.detector_path.is_file() and self.recognizer_path.is_file()):
            return False
        try:
            import cv2
            return hasattr(cv2, "FaceDetectorYN") and hasattr(cv2, "FaceRecognizerSF")
        except Exception:
            return False

    def status(self) -> dict[str, Any]:
        return {
            "backend": "opencv_sface",
            "available": self.available(),
            "detector_model": str(self.detector_path),
            "recognition_model": str(self.recognizer_path),
        }

    def _ensure(self):
        if self._detector is not None and self._recognizer is not None:
            return self._detector, self._recognizer
        if not self.available():
            raise FaceIdentityError(
                "Face identity models are not installed. See docs/PERSON_IDENTITY.md."
            )
        import cv2

        self._detector = cv2.FaceDetectorYN.create(
            str(self.detector_path),
            "",
            (320, 320),
            self.detector_score,
            self.detector_nms,
            self.detector_top_k,
        )
        self._recognizer = cv2.FaceRecognizerSF.create(str(self.recognizer_path), "")
        return self._detector, self._recognizer

    @staticmethod
    def _decode_jpeg(jpeg: bytes):
        import cv2
        arr = np.frombuffer(jpeg, dtype=np.uint8)
        image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if image is None:
            raise FaceIdentityError("Unable to decode Pi camera JPEG")
        return image

    def embedding_from_jpeg(self, jpeg: bytes) -> np.ndarray:
        detector, recognizer = self._ensure()
        image = self._decode_jpeg(jpeg)
        h, w = image.shape[:2]
        detector.setInputSize((w, h))
        _retval, faces = detector.detect(image)
        if faces is None or len(faces) == 0:
            raise FaceIdentityError("No face was detected in the current Pi frame")

        # Prefer the largest visible face; stage-one Pi perception is also
        # single-person oriented, so this tracks its primary-person assumption.
        face = max(faces, key=lambda row: float(row[2]) * float(row[3]))
        aligned = recognizer.alignCrop(image, np.asarray(face, dtype=np.float32).reshape(1, -1))
        feature = recognizer.feature(aligned)
        vec = np.asarray(feature, dtype=np.float32).reshape(-1)
        norm = float(np.linalg.norm(vec))
        if not np.isfinite(norm) or norm <= 1e-8:
            raise FaceIdentityError("Face recognizer produced an invalid embedding")
        return vec / norm
