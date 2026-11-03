from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from .util import safe_normalize


def _skew(axis: np.ndarray) -> np.ndarray:
    x, y, z = axis
    return np.array([[0.0, -z, y], [z, 0.0, -x], [-y, x, 0.0]], dtype=float)


def axis_angle_matrix(axis: np.ndarray, angle: float) -> np.ndarray:
    axis = safe_normalize(np.asarray(axis, dtype=float), np.array([0.0, 0.0, 1.0]))
    k = _skew(axis)
    eye = np.eye(3)
    return eye + np.sin(angle) * k + (1.0 - np.cos(angle)) * (k @ k)


def rpy_matrix(rpy: np.ndarray) -> np.ndarray:
    roll, pitch, yaw = [float(v) for v in rpy]
    cr, sr = np.cos(roll), np.sin(roll)
    cp, sp = np.cos(pitch), np.sin(pitch)
    cy, sy = np.cos(yaw), np.sin(yaw)
    rx = np.array([[1, 0, 0], [0, cr, -sr], [0, sr, cr]], dtype=float)
    ry = np.array([[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]], dtype=float)
    rz = np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1]], dtype=float)
    return rz @ ry @ rx


def transform(xyz: np.ndarray, rpy: np.ndarray) -> np.ndarray:
    t = np.eye(4)
    t[:3, :3] = rpy_matrix(np.asarray(rpy, dtype=float))
    t[:3, 3] = np.asarray(xyz, dtype=float)
    return t


def rotate(axis: np.ndarray, angle: float) -> np.ndarray:
    t = np.eye(4)
    t[:3, :3] = axis_angle_matrix(np.asarray(axis, dtype=float), angle)
    return t


@dataclass
class IKSolution:
    q: np.ndarray
    elbow_m: np.ndarray
    wrist_m: np.ndarray
    wrist_error_m: float
    elbow_error_m: float
    iterations: int
    converged: bool
    hit_limit: bool


class ArmChain:
    """URDF-style 4-DOF shoulder/elbow chain used by the current InMoov model."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.joints = list(config["joints"])
        self.endpoint = dict(config["endpoint"])
        self.lower = np.array([j["lower"] for j in self.joints], dtype=float)
        self.upper = np.array([j["upper"] for j in self.joints], dtype=float)
        self.neutral = np.clip(np.zeros(len(self.joints), dtype=float), self.lower, self.upper)
        _, elbow, wrist = self.forward(self.neutral)
        self.rest_shoulder_to_elbow_m = float(np.linalg.norm(elbow))
        self.rest_elbow_to_wrist_m = float(np.linalg.norm(wrist - elbow))

    def forward(self, q: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        q = np.asarray(q, dtype=float)
        t = np.eye(4)
        elbow = None
        joint_positions = []

        for angle, joint in zip(q, self.joints, strict=True):
            t = t @ transform(joint["origin_xyz_m"], joint["origin_rpy_rad"])
            joint_positions.append(t[:3, 3].copy())
            if joint.get("capture_point") == "elbow":
                elbow = t[:3, 3].copy()
            t = t @ rotate(joint["axis"], float(angle))

        t = t @ transform(self.endpoint["origin_xyz_m"], self.endpoint["origin_rpy_rad"])
        wrist = t[:3, 3].copy()
        if elbow is None:
            raise RuntimeError("Arm configuration has no elbow capture point")
        return np.asarray(joint_positions), elbow, wrist

    def _objective(self, q: np.ndarray, elbow_target: np.ndarray, wrist_target: np.ndarray, elbow_weight: float) -> np.ndarray:
        _, elbow, wrist = self.forward(q)
        return np.concatenate((wrist_target - wrist, elbow_weight * (elbow_target - elbow)))

    def solve(
        self,
        elbow_target_m: np.ndarray,
        wrist_target_m: np.ndarray,
        q0: np.ndarray | None = None,
        *,
        elbow_weight: float = 0.35,
        damping: float = 0.035,
        max_iterations: int = 35,
        step_limit_rad: float = 0.12,
        tolerance_m: float = 0.004,
    ) -> IKSolution:
        elbow_target_m = np.asarray(elbow_target_m, dtype=float)
        wrist_target_m = np.asarray(wrist_target_m, dtype=float)
        q = self.neutral.copy() if q0 is None else np.clip(np.asarray(q0, dtype=float), self.lower, self.upper)
        hit_limit = False
        converged = False
        eps = 1e-5

        iterations = 0
        for iterations in range(1, max_iterations + 1):
            err = self._objective(q, elbow_target_m, wrist_target_m, elbow_weight)
            if float(np.linalg.norm(err[:3])) <= tolerance_m:
                converged = True
                break

            jac = np.zeros((6, len(q)), dtype=float)
            for idx in range(len(q)):
                qp = q.copy()
                qp[idx] += eps
                ep = self._objective(qp, elbow_target_m, wrist_target_m, elbow_weight)
                # objective is target-current, so derivative wrt q has the opposite sign
                jac[:, idx] = (ep - err) / eps

            # We want err(q + dq) ~= 0: J*dq = -err.
            jt = jac.T
            lhs = jt @ jac + (damping * damping) * np.eye(len(q))
            rhs = -jt @ err
            try:
                dq = np.linalg.solve(lhs, rhs)
            except np.linalg.LinAlgError:
                dq = np.linalg.lstsq(lhs, rhs, rcond=None)[0]

            max_abs = float(np.max(np.abs(dq))) if dq.size else 0.0
            if max_abs > step_limit_rad:
                dq *= step_limit_rad / max_abs

            unclipped = q + dq
            clipped = np.clip(unclipped, self.lower, self.upper)
            if np.any(np.abs(clipped - unclipped) > 1e-9):
                hit_limit = True
            q = clipped

        _, elbow, wrist = self.forward(q)
        return IKSolution(
            q=q,
            elbow_m=elbow,
            wrist_m=wrist,
            wrist_error_m=float(np.linalg.norm(wrist_target_m - wrist)),
            elbow_error_m=float(np.linalg.norm(elbow_target_m - elbow)),
            iterations=iterations,
            converged=converged,
            hit_limit=hit_limit,
        )


def scaled_limb_targets(
    shoulder_m: np.ndarray,
    elbow_m: np.ndarray,
    wrist_m: np.ndarray,
    shoulder_to_elbow_length_m: float,
    elbow_to_wrist_length_m: float,
) -> tuple[np.ndarray, np.ndarray]:
    upper = safe_normalize(elbow_m - shoulder_m, np.array([0.0, 0.0, -1.0]))
    fore = safe_normalize(wrist_m - elbow_m, upper)
    elbow_target = upper * shoulder_to_elbow_length_m
    wrist_target = elbow_target + fore * elbow_to_wrist_length_m
    return elbow_target, wrist_target
