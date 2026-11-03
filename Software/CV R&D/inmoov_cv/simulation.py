from __future__ import annotations

"""Simulation-only motion shaping.

This module deliberately sits *after* the authoritative CV/IK retargeting layer.
The raw robot targets remain unchanged in ``frame['robot']``.  Blender consumes
``frame['simulation']`` so visual motion can resemble finite-speed servos without
changing the kinematic solution that will later feed real hardware.
"""

import copy
import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from .kinematics import ArmChain
from .collision import InterArmGuard
from .util import load_json
from pathlib import Path


@dataclass
class _State:
    position: float
    velocity: float = 0.0
    timestamp_s: float | None = None


class TrapezoidLimiter:
    """Acceleration-limited scalar motion toward a target, with no overshoot."""

    def __init__(self, initial: float = 0.0) -> None:
        self.initial = float(initial)
        self.state = _State(self.initial)

    def reset(self, value: float | None = None) -> None:
        self.state = _State(self.initial if value is None else float(value))

    def step(
        self,
        target: float,
        timestamp_s: float,
        max_velocity: float,
        max_acceleration: float,
    ) -> float:
        target = float(target)
        t = float(timestamp_s)
        vmax = max(abs(float(max_velocity)), 1e-6)
        amax = max(abs(float(max_acceleration)), 1e-6)
        s = self.state

        if s.timestamp_s is None:
            s.timestamp_s = t
            return s.position

        dt = max(min(t - s.timestamp_s, 0.100), 1e-4)
        s.timestamp_s = t
        error = target - s.position
        if abs(error) < 1e-7 and abs(s.velocity) < 1e-7:
            s.position = target
            s.velocity = 0.0
            return s.position

        direction = 1.0 if error >= 0.0 else -1.0
        # Braking-limited desired speed: sqrt(2*a*d) ensures there is room to stop.
        desired_speed = min(vmax, math.sqrt(max(0.0, 2.0 * amax * abs(error))))
        desired_velocity = direction * desired_speed

        dv = desired_velocity - s.velocity
        max_dv = amax * dt
        if dv > max_dv:
            s.velocity += max_dv
        elif dv < -max_dv:
            s.velocity -= max_dv
        else:
            s.velocity = desired_velocity

        step = s.velocity * dt
        if abs(step) >= abs(error) and step * error >= 0.0:
            s.position = target
            s.velocity = 0.0
        else:
            s.position += step
        return s.position


class SimulationMotionAdapter:
    """Build a servo-like simulation command tree from raw robot targets."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.cfg = config.get("simulation_motion", {})
        self.enabled = bool(self.cfg.get("enabled", True))
        self.speed_scale = max(float(self.cfg.get("speed_scale", 1.0)), 0.01)
        self.default_v = float(self.cfg.get("default_max_velocity_rad_s", 0.7853981634))
        self.default_a = float(self.cfg.get("default_max_acceleration_rad_s2", 2.0943951024))
        self.normalized_v = float(self.cfg.get("normalized_max_velocity_s", 0.50))
        self.normalized_a = float(self.cfg.get("normalized_max_acceleration_s2", 2.0))
        self._states: dict[str, TrapezoidLimiter] = {}
        self.collision_guard = None
        self.last_safe_arms = None

    def configure_collision(self, kinematics_path: str | Path, config: dict[str, Any] | None = None) -> None:
        kin = load_json(kinematics_path)
        arms = {side: ArmChain(kin['arms'][side]) for side in ('left','right')}
        self.collision_guard = InterArmGuard(arms, kin, config)
        self.last_safe_arms = {side: arms[side].neutral.copy() for side in arms}

    def reset(self) -> None:
        self._states.clear()
        if self.collision_guard is not None:
            self.last_safe_arms = {side: arm.neutral.copy() for side, arm in self.collision_guard.arms.items()}

    def _limit(self, key: str, target: float, t: float, *, normalized: bool = False) -> float:
        limiter = self._states.setdefault(key, TrapezoidLimiter(0.0))
        if not self.enabled:
            return float(target)
        if normalized:
            vmax = self.normalized_v * self.speed_scale
            amax = self.normalized_a * self.speed_scale
        else:
            vmax = self.default_v * self.speed_scale
            amax = self.default_a * self.speed_scale
        return limiter.step(target, t, vmax, amax)

    def adapt(self, raw_frame: dict[str, Any]) -> dict[str, Any]:
        """Return a profiled copy of ``raw_frame['robot']`` for visualization."""
        t = float(raw_frame.get("timestamp_s", 0.0))
        robot = copy.deepcopy(raw_frame.get("robot", {}))

        torso = robot.get("torso", {})
        if torso.get("valid"):
            torso["target_yaw_rad"] = float(torso.get("yaw_rad", 0.0))
            torso["target_bend_rad"] = float(torso.get("bend_rad", 0.0))
            torso["yaw_rad"] = self._limit("torso.yaw", torso["target_yaw_rad"], t)
            torso["bend_rad"] = self._limit("torso.bend", torso["target_bend_rad"], t)

        face = robot.get("face", {})
        if face.get("valid"):
            head = face.get("head", {})
            for field in ("turn_rad", "nod_rad", "tilt_rad"):
                target = float(head.get(field, 0.0))
                head[f"target_{field}"] = target
                head[field] = self._limit(f"face.head.{field}", target, t)
            eyes = face.get("eyes", {})
            for side in ("left", "right"):
                eye = eyes.get(side, {})
                for field in ("pan_rad", "tilt_rad"):
                    target = float(eye.get(field, 0.0))
                    eye[f"target_{field}"] = target
                    eye[field] = self._limit(f"face.eye.{side}.{field}", target, t)
            target_jaw = float(face.get("jaw_rad", 0.0))
            face["target_jaw_rad"] = target_jaw
            face["jaw_rad"] = self._limit("face.jaw", target_jaw, t)
            lids = face.get("eyelids", {})
            for side in ("left_closed", "right_closed"):
                if side in lids:
                    lids[side] = self._limit(f"face.eyelid.{side}", float(lids[side]), t, normalized=True)

        for side, arm in robot.get("arms", {}).items():
            if not arm.get("valid"):
                continue
            raw = [float(v) for v in arm.get("joint_angles_rad", [])]
            arm["target_joint_angles_rad"] = list(raw)
            arm["joint_angles_rad"] = [
                self._limit(f"arm.{side}.q{i}", value, t) for i, value in enumerate(raw)
            ]

        for side, hand in robot.get("hands", {}).items():
            if not hand.get("valid"):
                continue
            curls = dict(hand.get("curls", {}))
            hand["target_curls"] = dict(curls)
            hand["curls"] = {
                name: self._limit(f"hand.{side}.curl.{name}", float(value), t, normalized=True)
                for name, value in curls.items()
            }
            wrist = hand.get("wrist", {})
            if wrist.get("valid"):
                for field in ("rotation_rad", "bend_rad"):
                    target = float(wrist.get(field, 0.0))
                    wrist[f"target_{field}"] = target
                    wrist[field] = self._limit(f"hand.{side}.wrist.{field}", target, t)

        if self.collision_guard is not None:
            arm_data = robot.get('arms', {})
            candidates = {}
            for side in ('left', 'right'):
                entry = arm_data.get(side, {})
                candidates[side] = np.asarray(entry['joint_angles_rad'], dtype=float) if entry.get('valid') else self.last_safe_arms[side]
            result = self.collision_guard.path(self.last_safe_arms, candidates)
            if result['blocked']:
                for side in ('left', 'right'):
                    entry = arm_data.get(side, {})
                    if entry.get('valid'):
                        entry['joint_angles_rad'] = self.last_safe_arms[side].tolist()
                        entry['collision_held'] = True
                        for i, v in enumerate(self.last_safe_arms[side]):
                            self._states[f'arm.{side}.q{i}'].reset(float(v))
            else:
                for side in ('left', 'right'):
                    if arm_data.get(side, {}).get('valid'):
                        self.last_safe_arms[side] = candidates[side].copy()
            robot['collision'] = result | {'physical_safety_certified': False}
        return robot
