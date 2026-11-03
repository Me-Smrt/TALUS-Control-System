from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

from .util import clamp, clamp01


@dataclass
class FaceState:
    valid: bool = False
    yaw_rad: float = 0.0
    pitch_rad: float = 0.0
    roll_rad: float = 0.0
    left_eyelid_closed: float = 0.0
    right_eyelid_closed: float = 0.0
    left_gaze_x: float = 0.0
    left_gaze_y: float = 0.0
    right_gaze_x: float = 0.0
    right_gaze_y: float = 0.0
    jaw_open: float = 0.0
    blendshapes: dict[str, float] = field(default_factory=dict)
    normalized_landmarks: list[list[float]] = field(default_factory=list)


class FaceAnalyzer:
    # 3D reference is deliberately generic; automatic neutral calibration removes
    # subject/camera mounting offsets. It is used only for head orientation.
    _MODEL_POINTS = np.array(
        [
            [0.0, 0.0, 0.0],
            [0.0, -63.6, -12.5],
            [-43.3, 32.7, -26.0],
            [43.3, 32.7, -26.0],
            [-28.9, -28.9, -24.1],
            [28.9, -28.9, -24.1],
        ],
        dtype=np.float64,
    )
    _FACE_INDICES = (1, 152, 33, 263, 61, 291)

    def __init__(self, calibration_frames: int = 30) -> None:
        self.calibration_frames = max(1, int(calibration_frames))
        self._neutral_samples: list[np.ndarray] = []
        self._neutral = np.zeros(3, dtype=float)

    def reset_neutral(self) -> None:
        self._neutral_samples.clear()
        self._neutral[:] = 0.0

    @staticmethod
    def _blendshape_map(result: Any) -> dict[str, float]:
        categories = getattr(result, "face_blendshapes", None) or []
        out: dict[str, float] = {}
        for category in categories:
            name = getattr(category, "category_name", None) or getattr(category, "display_name", None)
            score = getattr(category, "score", None)
            if name and score is not None:
                out[str(name)] = float(score)
        return out

    @staticmethod
    def _bs(bs: dict[str, float], name: str) -> float:
        return float(bs.get(name, 0.0))

    def _head_pose(self, landmarks: list[Any], width: int, height: int) -> np.ndarray | None:
        if len(landmarks) <= max(self._FACE_INDICES):
            return None
        image_points = np.array(
            [[landmarks[i].x * width, landmarks[i].y * height] for i in self._FACE_INDICES],
            dtype=np.float64,
        )
        focal = float(max(width, height))
        camera_matrix = np.array(
            [[focal, 0.0, width / 2.0], [0.0, focal, height / 2.0], [0.0, 0.0, 1.0]],
            dtype=np.float64,
        )
        ok, rotation_vector, _translation = cv2.solvePnP(
            self._MODEL_POINTS,
            image_points,
            camera_matrix,
            np.zeros((4, 1), dtype=np.float64),
            flags=cv2.SOLVEPNP_ITERATIVE,
        )
        if not ok:
            return None
        rotation_matrix, _ = cv2.Rodrigues(rotation_vector)
        angles_deg = cv2.RQDecomp3x3(rotation_matrix)[0]
        # OpenCV returns rotations around camera X/Y/Z. Convert to intuitive
        # pitch/yaw/roll and neutral-calibrate before robot retargeting.
        pitch, yaw, roll = [math.radians(float(v)) for v in angles_deg]
        return np.array([yaw, pitch, roll], dtype=float)

    def analyze(self, result: Any, frame_shape: tuple[int, ...]) -> FaceState:
        landmarks = getattr(result, "face_landmarks", None) or []
        if not landmarks:
            return FaceState(valid=False)

        bs = self._blendshape_map(result)
        height, width = frame_shape[:2]
        orientation = self._head_pose(landmarks, width, height)
        if orientation is None:
            orientation = np.zeros(3, dtype=float)

        if len(self._neutral_samples) < self.calibration_frames:
            self._neutral_samples.append(orientation.copy())
            self._neutral = np.median(np.stack(self._neutral_samples), axis=0)
        relative = orientation - self._neutral

        left_gaze_x = self._bs(bs, "eyeLookOutLeft") - self._bs(bs, "eyeLookInLeft")
        right_gaze_x = self._bs(bs, "eyeLookInRight") - self._bs(bs, "eyeLookOutRight")
        left_gaze_y = self._bs(bs, "eyeLookUpLeft") - self._bs(bs, "eyeLookDownLeft")
        right_gaze_y = self._bs(bs, "eyeLookUpRight") - self._bs(bs, "eyeLookDownRight")

        return FaceState(
            valid=True,
            yaw_rad=float(relative[0]),
            pitch_rad=float(relative[1]),
            roll_rad=float(relative[2]),
            left_eyelid_closed=clamp01(self._bs(bs, "eyeBlinkLeft")),
            right_eyelid_closed=clamp01(self._bs(bs, "eyeBlinkRight")),
            left_gaze_x=clamp(left_gaze_x, -1.0, 1.0),
            left_gaze_y=clamp(left_gaze_y, -1.0, 1.0),
            right_gaze_x=clamp(right_gaze_x, -1.0, 1.0),
            right_gaze_y=clamp(right_gaze_y, -1.0, 1.0),
            jaw_open=clamp01(self._bs(bs, "jawOpen")),
            blendshapes=bs,
            normalized_landmarks=[[float(p.x), float(p.y), float(p.z)] for p in landmarks],
        )
