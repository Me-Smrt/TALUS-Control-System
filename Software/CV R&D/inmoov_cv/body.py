from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .util import angle_between


# MediaPipe Pose landmark indices.
NOSE = 0
LEFT_SHOULDER, RIGHT_SHOULDER = 11, 12
LEFT_ELBOW, RIGHT_ELBOW = 13, 14
LEFT_WRIST, RIGHT_WRIST = 15, 16
LEFT_HIP, RIGHT_HIP = 23, 24
LEFT_KNEE, RIGHT_KNEE = 25, 26
LEFT_ANKLE, RIGHT_ANKLE = 27, 28


@dataclass
class BodyState:
    valid: bool = False
    normalized_landmarks: list[list[float]] = field(default_factory=list)
    world_landmarks_m: list[list[float]] = field(default_factory=list)
    visibility: list[float] = field(default_factory=list)
    joint_metrics_rad: dict[str, float] = field(default_factory=dict)

    def world(self, index: int) -> np.ndarray:
        return np.asarray(self.world_landmarks_m[index], dtype=float)


class BodyAnalyzer:
    @staticmethod
    def _point3(landmark: Any) -> list[float]:
        return [float(landmark.x), float(landmark.y), float(landmark.z)]

    @staticmethod
    def _visibility(landmark: Any) -> float:
        value = getattr(landmark, "visibility", None)
        return float(value) if value is not None else 1.0

    @staticmethod
    def _flexion(points: list[list[float]], a: int, b: int, c: int) -> float:
        pa, pb, pc = (np.asarray(points[i], dtype=float) for i in (a, b, c))
        internal = angle_between(pa - pb, pc - pb)
        return float(np.pi - internal)

    def analyze(self, result: Any) -> BodyState:
        normalized = getattr(result, "pose_landmarks", None) or []
        world = getattr(result, "pose_world_landmarks", None) or []
        if len(world) < 33 or len(normalized) < 33:
            return BodyState(valid=False)

        norm_points = [self._point3(p) for p in normalized]
        world_points = [self._point3(p) for p in world]
        visibility = [self._visibility(p) for p in normalized]

        metrics = {
            "left_elbow_flexion": self._flexion(world_points, LEFT_SHOULDER, LEFT_ELBOW, LEFT_WRIST),
            "right_elbow_flexion": self._flexion(world_points, RIGHT_SHOULDER, RIGHT_ELBOW, RIGHT_WRIST),
            "left_knee_flexion": self._flexion(world_points, LEFT_HIP, LEFT_KNEE, LEFT_ANKLE),
            "right_knee_flexion": self._flexion(world_points, RIGHT_HIP, RIGHT_KNEE, RIGHT_ANKLE),
        }
        return BodyState(
            valid=True,
            normalized_landmarks=norm_points,
            world_landmarks_m=world_points,
            visibility=visibility,
            joint_metrics_rad=metrics,
        )
