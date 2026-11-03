from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .util import angle_between, clamp01, safe_normalize


FINGER_CHAINS = {
    "thumb": (1, 2, 3, 4),
    "index": (5, 6, 7, 8),
    "middle": (9, 10, 11, 12),
    "ring": (13, 14, 15, 16),
    "pinky": (17, 18, 19, 20),
}


@dataclass
class HandState:
    valid: bool = False
    normalized_landmarks: list[list[float]] = field(default_factory=list)
    world_landmarks_m: list[list[float]] = field(default_factory=list)
    curls: dict[str, float] = field(default_factory=dict)
    palm_basis: list[list[float]] = field(default_factory=list)


class HandAnalyzer:
    @staticmethod
    def _points(landmarks: list[Any]) -> list[list[float]]:
        return [[float(p.x), float(p.y), float(p.z)] for p in landmarks]

    @staticmethod
    def _curl_at(points: np.ndarray, a: int, b: int, c: int) -> float:
        internal = angle_between(points[a] - points[b], points[c] - points[b])
        # straight ~= pi, strongly curled ~= pi/3 or less
        return clamp01((np.pi - internal) / (2.0 * np.pi / 3.0))

    def _finger_curls(self, points_list: list[list[float]]) -> dict[str, float]:
        points = np.asarray(points_list, dtype=float)
        out: dict[str, float] = {}
        # Thumb behaves differently; use MCP + IP bends.
        out["thumb"] = float(
            0.45 * self._curl_at(points, 1, 2, 3)
            + 0.55 * self._curl_at(points, 2, 3, 4)
        )
        for name, chain in FINGER_CHAINS.items():
            if name == "thumb":
                continue
            mcp, pip, dip, tip = chain
            out[name] = float(
                0.25 * self._curl_at(points, 0, mcp, pip)
                + 0.45 * self._curl_at(points, mcp, pip, dip)
                + 0.30 * self._curl_at(points, pip, dip, tip)
            )
        return out

    @staticmethod
    def _palm_basis(points_list: list[list[float]]) -> list[list[float]]:
        points = np.asarray(points_list, dtype=float)
        wrist = points[0]
        index_mcp = points[5]
        middle_mcp = points[9]
        pinky_mcp = points[17]
        x_axis = safe_normalize(index_mcp - pinky_mcp, np.array([1.0, 0.0, 0.0]))
        y_axis = safe_normalize(middle_mcp - wrist, np.array([0.0, -1.0, 0.0]))
        z_axis = safe_normalize(np.cross(x_axis, y_axis), np.array([0.0, 0.0, 1.0]))
        y_axis = safe_normalize(np.cross(z_axis, x_axis), y_axis)
        return np.column_stack((x_axis, y_axis, z_axis)).tolist()

    def _one(self, normalized: list[Any], world: list[Any]) -> HandState:
        if len(normalized) < 21:
            return HandState(valid=False)
        norm_points = self._points(normalized)
        world_points = self._points(world) if len(world) >= 21 else norm_points
        return HandState(
            valid=True,
            normalized_landmarks=norm_points,
            world_landmarks_m=world_points,
            curls=self._finger_curls(world_points),
            palm_basis=self._palm_basis(world_points),
        )

    def analyze(self, result: Any) -> dict[str, HandState]:
        return {
            "left": self._one(
                getattr(result, "left_hand_landmarks", None) or [],
                getattr(result, "left_hand_world_landmarks", None) or [],
            ),
            "right": self._one(
                getattr(result, "right_hand_landmarks", None) or [],
                getattr(result, "right_hand_world_landmarks", None) or [],
            ),
        }
