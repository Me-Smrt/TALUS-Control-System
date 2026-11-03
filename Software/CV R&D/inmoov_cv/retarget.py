from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np

from .body import (
    LEFT_ELBOW,
    LEFT_HIP,
    LEFT_SHOULDER,
    LEFT_WRIST,
    RIGHT_ELBOW,
    RIGHT_HIP,
    RIGHT_SHOULDER,
    RIGHT_WRIST,
    BodyState,
)
from .face import FaceState
from .filters import FilterBank
from .hands import HandState
from .kinematics import ArmChain, scaled_limb_targets
from .collision import InterArmGuard
from .util import clamp, load_json, safe_normalize


SIDE_INDICES = {
    "left": (LEFT_SHOULDER, LEFT_ELBOW, LEFT_WRIST),
    "right": (RIGHT_SHOULDER, RIGHT_ELBOW, RIGHT_WRIST),
}


def mp_world_to_robot_camera(point: np.ndarray) -> np.ndarray:
    """Map MediaPipe camera coordinates into the InMoov/Blender convention."""
    p = np.asarray(point, dtype=float)
    return np.array([p[0], p[2], -p[1]], dtype=float)


def _signed_angle(a: np.ndarray, b: np.ndarray, axis: np.ndarray) -> float:
    a = safe_normalize(np.asarray(a, dtype=float), np.array([1.0, 0.0, 0.0]))
    b = safe_normalize(np.asarray(b, dtype=float), a)
    axis = safe_normalize(np.asarray(axis, dtype=float), np.array([0.0, 0.0, 1.0]))
    return math.atan2(float(np.dot(np.cross(a, b), axis)), float(np.dot(a, b)))


def _wrap_pi(angle: float) -> float:
    return (float(angle) + math.pi) % (2.0 * math.pi) - math.pi


def torso_basis(body: BodyState) -> tuple[np.ndarray, float, float, float] | None:
    """Return torso basis plus yaw, lateral lean, and sagittal lean.

    In the current maintained URDF the topStom joint rotates about an axis that
    is nearly world -Y at rest. With X=lateral, Y=front/back, Z=up, that is a
    lateral/side-bend DOF. Sagittal forward/back lean is retained as a tracked
    diagnostic rather than being forced onto the wrong robot axis.
    """
    if not body.valid:
        return None
    left_shoulder = mp_world_to_robot_camera(body.world(LEFT_SHOULDER))
    right_shoulder = mp_world_to_robot_camera(body.world(RIGHT_SHOULDER))
    left_hip = mp_world_to_robot_camera(body.world(LEFT_HIP))
    right_hip = mp_world_to_robot_camera(body.world(RIGHT_HIP))

    x_axis = safe_normalize(left_shoulder - right_shoulder, np.array([1.0, 0.0, 0.0]))
    shoulder_center = (left_shoulder + right_shoulder) * 0.5
    hip_center = (left_hip + right_hip) * 0.5
    z_hint = safe_normalize(shoulder_center - hip_center, np.array([0.0, 0.0, 1.0]))
    y_axis = safe_normalize(np.cross(z_hint, x_axis), np.array([0.0, 1.0, 0.0]))
    z_axis = safe_normalize(np.cross(x_axis, y_axis), z_hint)
    basis = np.column_stack((x_axis, y_axis, z_axis))

    yaw = math.atan2(float(x_axis[1]), float(x_axis[0]))
    # Lateral lean: torso-up vector tipped into X; this is the motion represented
    # by the current topStom rotation axis.
    lateral_lean = math.atan2(float(z_axis[0]), float(z_axis[2]))
    # Sagittal lean (forward/back) is tracked but has no matching DOF in this URDF.
    sagittal_lean = math.atan2(float(-z_axis[1]), float(z_axis[2]))
    return basis, yaw, lateral_lean, sagittal_lean


class RobotRetargeter:
    def __init__(self, config: dict[str, Any], kinematics_path: str | Path) -> None:
        self.config = config
        self.kin = load_json(kinematics_path)
        self.arms = {side: ArmChain(self.kin["arms"][side]) for side in ("left", "right")}
        smooth = config["smoothing"]
        self.filters = FilterBank(
            float(smooth["min_cutoff"]),
            float(smooth["beta"]),
            float(smooth["derivative_cutoff"]),
        )
        self.last_q = {side: self.arms[side].neutral.copy() for side in self.arms}
        self.collision_guard = InterArmGuard(self.arms, self.kin, config.get("collision_guard", {}))
        self.last_safe_q = {side: arm.neutral.copy() for side, arm in self.arms.items()}
        self.eye_test_enabled = False
        self._wrist_neutral_samples: dict[str, list[tuple[float, float]]] = {"left": [], "right": []}
        self._wrist_neutral: dict[str, tuple[float, float]] = {"left": (0.0, 0.0), "right": (0.0, 0.0)}

    def reset_filters(self) -> None:
        self.filters.reset()
        self.last_q = {side: self.arms[side].neutral.copy() for side in self.arms}
        self.last_safe_q = {side: self.arms[side].neutral.copy() for side in self.arms}

    def reset_wrist_neutral(self) -> None:
        self._wrist_neutral_samples = {"left": [], "right": []}
        self._wrist_neutral = {"left": (0.0, 0.0), "right": (0.0, 0.0)}

    def toggle_eye_test(self) -> bool:
        self.eye_test_enabled = not self.eye_test_enabled
        return self.eye_test_enabled

    def _f(self, key: str, value: float, timestamp_s: float) -> float:
        return self.filters.value(key, float(value), timestamp_s)

    def _filter_vec(self, key: str, value: np.ndarray, timestamp_s: float) -> np.ndarray:
        return np.array(
            [self._f(f"{key}.{i}", float(v), timestamp_s) for i, v in enumerate(value)],
            dtype=float,
        )

    @staticmethod
    def _deadzone(value: float, deadzone: float) -> float:
        v = float(value)
        d = max(0.0, min(0.95, float(deadzone)))
        if abs(v) <= d:
            return 0.0
        return math.copysign((abs(v) - d) / (1.0 - d), v)

    def _face_commands(self, face: FaceState, torso_yaw: float, torso_bend: float, t: float) -> dict[str, Any]:
        r = self.config["retarget"]
        mirror = bool(r.get("mirror_motion", False))
        if not face.valid or not bool(r.get("apply_face", True)):
            return {"valid": False}

        yaw = -face.yaw_rad if mirror else face.yaw_rad
        roll = -face.roll_rad if mirror else face.roll_rad
        turn = yaw - torso_yaw
        nod = face.pitch_rad - torso_bend
        tilt = roll

        head_cfg = self.kin["head"]
        turn = clamp(turn, head_cfg["turn"]["lower"], head_cfg["turn"]["upper"])
        nod = clamp(nod, head_cfg["nod"]["lower"], head_cfg["nod"]["upper"])
        tilt = clamp(tilt, head_cfg["tilt"]["lower"], head_cfg["tilt"]["upper"])

        deadzone = float(r.get("gaze_deadzone", 0.02))
        pan_gain = float(r.get("gaze_pan_gain", 1.6))
        tilt_gain = float(r.get("gaze_tilt_gain", 1.4))

        if mirror:
            left_x, right_x = -face.right_gaze_x, -face.left_gaze_x
            left_y, right_y = face.right_gaze_y, face.left_gaze_y
            left_lid, right_lid = face.right_eyelid_closed, face.left_eyelid_closed
        else:
            left_x, right_x = face.left_gaze_x, face.right_gaze_x
            left_y, right_y = face.left_gaze_y, face.right_gaze_y
            left_lid, right_lid = face.left_eyelid_closed, face.right_eyelid_closed

        eyes_cfg = self.kin["eyes"]

        def eye(side: str, x: float, y: float) -> dict[str, float]:
            pan_key = f"{side}_pan"
            tilt_key = f"{side}_tilt"
            if self.eye_test_enabled:
                pan_limit = max(abs(eyes_cfg[pan_key]["lower"]), abs(eyes_cfg[pan_key]["upper"]))
                tilt_limit = max(abs(eyes_cfg[tilt_key]["lower"]), abs(eyes_cfg[tilt_key]["upper"]))
                pan = 0.80 * pan_limit * math.sin(t * 2.0 * math.pi * 0.25)
                eye_tilt = 0.45 * tilt_limit * math.sin(t * 2.0 * math.pi * 0.17 + 0.9)
            else:
                pan_norm = self._deadzone(x, deadzone) * pan_gain * float(r.get(f"{side}_eye_pan_sign", 1.0))
                tilt_norm = self._deadzone(y, deadzone) * tilt_gain * float(r.get(f"{side}_eye_tilt_sign", 1.0))
                pan_limit = max(abs(eyes_cfg[pan_key]["lower"]), abs(eyes_cfg[pan_key]["upper"]))
                tilt_limit = max(abs(eyes_cfg[tilt_key]["lower"]), abs(eyes_cfg[tilt_key]["upper"]))
                pan = clamp(pan_norm * pan_limit, eyes_cfg[pan_key]["lower"], eyes_cfg[pan_key]["upper"])
                eye_tilt = clamp(tilt_norm * tilt_limit, eyes_cfg[tilt_key]["lower"], eyes_cfg[tilt_key]["upper"])
            return {
                "pan_rad": self._f(f"face.eye.{side}.pan", pan, t),
                "tilt_rad": self._f(f"face.eye.{side}.tilt", eye_tilt, t),
                "source_gaze_x": float(x),
                "source_gaze_y": float(y),
            }

        jaw_cfg = self.kin["jaw"]
        jaw = jaw_cfg["lower"] + face.jaw_open * (jaw_cfg["upper"] - jaw_cfg["lower"])

        return {
            "valid": True,
            "head": {
                "turn_rad": self._f("face.head.turn", turn, t),
                "nod_rad": self._f("face.head.nod", nod, t),
                "tilt_rad": self._f("face.head.tilt", tilt, t),
            },
            "eyes": {"left": eye("left", left_x, left_y), "right": eye("right", right_x, right_y)},
            "eye_test_enabled": self.eye_test_enabled,
            "jaw_rad": self._f("face.jaw", jaw, t),
            "eyelids": {
                "left_closed": self._f("face.eyelid.left", left_lid, t),
                "right_closed": self._f("face.eyelid.right", right_lid, t),
            },
            "expression_blendshapes": face.blendshapes,
        }

    def _arm_command(self, robot_side: str, source_side: str, body: BodyState, basis: np.ndarray, t: float) -> dict[str, Any]:
        r = self.config["retarget"]
        if not body.valid or not bool(r.get("apply_arms", True)):
            return {"valid": False}

        shoulder_i, elbow_i, wrist_i = SIDE_INDICES[source_side]
        if min(body.visibility[shoulder_i], body.visibility[elbow_i], body.visibility[wrist_i]) < 0.35:
            return {"valid": False, "reason": "low_visibility"}

        shoulder = mp_world_to_robot_camera(body.world(shoulder_i))
        elbow = mp_world_to_robot_camera(body.world(elbow_i))
        wrist = mp_world_to_robot_camera(body.world(wrist_i))

        shoulder_local = basis.T @ shoulder
        elbow_local = basis.T @ elbow
        wrist_local = basis.T @ wrist

        if bool(r.get("mirror_motion", False)):
            shoulder_local[0] *= -1.0
            elbow_local[0] *= -1.0
            wrist_local[0] *= -1.0

        chain = self.arms[robot_side]
        elbow_target, wrist_target = scaled_limb_targets(
            shoulder_local,
            elbow_local,
            wrist_local,
            chain.rest_shoulder_to_elbow_m,
            chain.rest_elbow_to_wrist_m,
        )
        elbow_target = self._filter_vec(f"arm.{robot_side}.elbow_target", elbow_target, t)
        wrist_target = self._filter_vec(f"arm.{robot_side}.wrist_target", wrist_target, t)

        solution = chain.solve(
            elbow_target,
            wrist_target,
            self.last_q[robot_side],
            elbow_weight=float(r.get("arm_elbow_weight", 0.35)),
            damping=float(r.get("arm_damping", 0.035)),
            max_iterations=int(r.get("arm_max_iterations", 35)),
            step_limit_rad=float(r.get("arm_step_limit_rad", 0.12)),
        )
        self.last_q[robot_side] = solution.q.copy()

        return {
            "valid": True,
            "source_side": source_side,
            "wrist_target_from_shoulder_mm": (wrist_target * 1000.0).tolist(),
            "elbow_target_from_shoulder_mm": (elbow_target * 1000.0).tolist(),
            "joint_names": [j["name"] for j in chain.joints],
            "joint_angles_rad": solution.q.tolist(),
            "wrist_error_mm": solution.wrist_error_m * 1000.0,
            "elbow_error_mm": solution.elbow_error_m * 1000.0,
            "iterations": solution.iterations,
            "converged": solution.converged,
            "hit_limit": solution.hit_limit,
        }

    def _wrist_command(self, robot_side: str, source_side: str, body: BodyState, hand: HandState, t: float) -> dict[str, Any]:
        r = self.config["retarget"]
        if not body.valid or not hand.valid or not bool(r.get("apply_wrists", True)):
            return {"valid": False}
        _, elbow_i, wrist_i = SIDE_INDICES[source_side]
        if min(body.visibility[elbow_i], body.visibility[wrist_i]) < 0.35:
            return {"valid": False, "reason": "low_visibility"}
        if not hand.palm_basis:
            return {"valid": False, "reason": "no_palm_basis"}

        fore = safe_normalize(body.world(wrist_i) - body.world(elbow_i), np.array([0.0, 0.0, -1.0]))
        palm = np.asarray(hand.palm_basis, dtype=float)
        palm_x = safe_normalize(palm[:, 0], np.array([1.0, 0.0, 0.0]))
        palm_long = safe_normalize(palm[:, 1], fore)
        palm_normal = safe_normalize(palm[:, 2], np.array([0.0, 0.0, 1.0]))

        shoulder_center = (body.world(LEFT_SHOULDER) + body.world(RIGHT_SHOULDER)) * 0.5
        hip_center = (body.world(LEFT_HIP) + body.world(RIGHT_HIP)) * 0.5
        torso_up = safe_normalize(shoulder_center - hip_center, np.array([0.0, -1.0, 0.0]))

        ref = torso_up - fore * float(np.dot(torso_up, fore))
        if float(np.linalg.norm(ref)) < 1e-5:
            camera_x = np.array([1.0, 0.0, 0.0])
            ref = camera_x - fore * float(np.dot(camera_x, fore))
        ref = safe_normalize(ref, np.array([1.0, 0.0, 0.0]))
        normal_proj = palm_normal - fore * float(np.dot(palm_normal, fore))
        normal_proj = safe_normalize(normal_proj, ref)
        raw_rotation = _signed_angle(ref, normal_proj, fore)

        # Wrist flex/extension around the palm's lateral axis. The maintained
        # InMoov model exposes only 0..90 deg, so negative human extension is
        # tracked but cannot be commanded into the current robot DOF.
        raw_bend = _signed_angle(fore, palm_long, palm_x)

        samples = self._wrist_neutral_samples[source_side]
        frames = max(1, int(r.get("wrist_neutral_calibration_frames", 30)))
        if len(samples) < frames:
            samples.append((raw_rotation, raw_bend))
            # Circular mean for axial rotation, ordinary median-like mean for small bend.
            s = sum(math.sin(v[0]) for v in samples)
            c = sum(math.cos(v[0]) for v in samples)
            rot0 = math.atan2(s, c)
            bend0 = float(np.median([v[1] for v in samples]))
            self._wrist_neutral[source_side] = (rot0, bend0)

        rot0, bend0 = self._wrist_neutral[source_side]
        rotation = _wrap_pi(raw_rotation - rot0)
        bend_relative = _wrap_pi(raw_bend - bend0)

        mirror = bool(r.get("mirror_motion", False))
        if mirror:
            rotation = -rotation
        rotation *= float(r.get(f"{robot_side}_wrist_rotation_sign", 1.0))
        bend_relative *= float(r.get(f"{robot_side}_wrist_bend_sign", 1.0))

        wrist_cfg = self.kin["arms"][robot_side]
        rz = wrist_cfg["wrist_rotation_z"]
        bx = wrist_cfg["wrist_bend_x"]
        rotation = clamp(rotation, rz["lower"], rz["upper"])
        # This is intentionally one-sided because the current published robot joint is.
        bend = clamp(max(0.0, bend_relative), bx["lower"], bx["upper"])

        return {
            "valid": True,
            "rotation_joint_name": rz.get("joint_name", f"{robot_side}_wrist_z"),
            "bend_joint_name": bx.get("joint_name", f"i01.{robot_side}Hand.wrist.001"),
            "rotation_rad": self._f(f"wrist.{robot_side}.rotation", rotation, t),
            "bend_rad": self._f(f"wrist.{robot_side}.bend", bend, t),
            "tracked_raw_rotation_rad": float(raw_rotation),
            "tracked_raw_bend_rad": float(raw_bend),
            "negative_bend_unrepresentable": bool(bend_relative < 0.0),
            "calibrating": len(samples) < frames,
        }

    def _hand_command(self, robot_side: str, source_side: str, body: BodyState, hands: dict[str, HandState], t: float) -> dict[str, Any]:
        if not bool(self.config["retarget"].get("apply_hands", True)):
            return {"valid": False}
        hand = hands[source_side]
        if not hand.valid:
            return {"valid": False}
        curls = {name: self._f(f"hand.{robot_side}.{name}", value, t) for name, value in hand.curls.items()}
        return {
            "valid": True,
            "source_side": source_side,
            "curls": curls,
            "wrist": self._wrist_command(robot_side, source_side, body, hand, t),
        }

    def retarget(self, timestamp_s: float, face: FaceState, body: BodyState, hands: dict[str, HandState]) -> dict[str, Any]:
        t = float(timestamp_s)
        r = self.config["retarget"]
        mirror = bool(r.get("mirror_motion", False))
        basis_data = torso_basis(body)

        torso_yaw = 0.0
        torso_bend = 0.0
        torso_sagittal_lean = 0.0
        basis = np.eye(3)
        torso_valid = False
        if basis_data is not None and bool(r.get("apply_torso", True)):
            basis, raw_yaw, raw_lateral_lean, raw_sagittal_lean = basis_data
            raw_yaw *= float(r.get("torso_yaw_sign", 1.0)) * float(r.get("torso_yaw_gain", 1.0))
            if mirror:
                raw_yaw = -raw_yaw
                raw_lateral_lean = -raw_lateral_lean
            raw_bend = raw_lateral_lean * float(r.get("torso_bend_sign", 1.0)) * float(r.get("torso_bend_gain", 1.0))
            deadzone = float(r.get("torso_deadzone_rad", math.radians(1.0)))
            if abs(raw_yaw) < deadzone:
                raw_yaw = 0.0
            if abs(raw_bend) < deadzone:
                raw_bend = 0.0
            tc = self.kin["torso"]
            torso_yaw = clamp(raw_yaw, tc["yaw"]["lower"], tc["yaw"]["upper"])
            torso_bend = clamp(raw_bend, tc["bend"]["lower"], tc["bend"]["upper"])
            torso_yaw = self._f("torso.yaw", torso_yaw, t)
            torso_bend = self._f("torso.bend", torso_bend, t)
            torso_sagittal_lean = self._f("torso.sagittal_lean", raw_sagittal_lean, t)
            torso_valid = True

        source_for_robot = {
            "left": "right" if mirror else "left",
            "right": "left" if mirror else "right",
        }

        arms = {
            robot_side: self._arm_command(robot_side, source_for_robot[robot_side], body, basis, t)
            for robot_side in ("left", "right")
        }
        # Reject unstable IK solutions before collision evaluation. MediaPipe
        # depth/occlusion can produce large but numerically finite joint jumps.
        # These rejected poses may be logged, but must not advance the solver's
        # accepted seed or make it into Blender's commanded joint tree.
        stability = self.config.get("retarget_stability", {})
        if bool(stability.get("enabled", True)):
            max_jump = float(stability.get("max_joint_jump_rad", 0.90))
            max_wrist = float(stability.get("max_wrist_error_mm", 260.0))
            max_elbow = float(stability.get("max_elbow_error_mm", 300.0))
            for side, arm in arms.items():
                if not arm.get("valid"):
                    self.last_q[side] = self.last_safe_q[side].copy()
                    continue
                candidate_q = np.asarray(arm["joint_angles_rad"], dtype=float)
                jump = float(np.max(np.abs(candidate_q - self.last_safe_q[side])))
                wrist_err = float(arm.get("wrist_error_mm", 0.0))
                elbow_err = float(arm.get("elbow_error_mm", 0.0))
                reason = ("nonfinite_ik" if not np.all(np.isfinite(candidate_q)) else
                          "joint_jump" if jump > max_jump else
                          "wrist_fit_error" if wrist_err > max_wrist else
                          "elbow_fit_error" if elbow_err > max_elbow else None)
                if reason:
                    arm["tracking_rejected"] = reason
                    arm["collision_held"] = True
                    arm["joint_angles_rad"] = self.last_safe_q[side].tolist()
                    self.last_q[side] = self.last_safe_q[side].copy()

        # Reject inter-arm capsule intersections and sampled swept paths before
        # the Blender/physical backend sees the new IK targets. Invalid or
        # absent arms do not authorize new motion on the missing side.
        candidate = {side: np.asarray(arms[side].get("joint_angles_rad", self.last_safe_q[side]), dtype=float)
                     for side in ("left", "right")}
        guard_status = self.collision_guard.path(self.last_safe_q, candidate)
        if guard_status["blocked"]:
            for side in ("left", "right"):
                if arms[side].get("valid"):
                    arms[side]["joint_angles_rad"] = self.last_safe_q[side].tolist()
                    arms[side]["collision_held"] = True
                    self.last_q[side] = self.last_safe_q[side].copy()
        else:
            for side in ("left", "right"):
                if arms[side].get("valid"):
                    self.last_safe_q[side] = candidate[side].copy()
        hand_cmds = {
            robot_side: self._hand_command(robot_side, source_for_robot[robot_side], body, hands, t)
            for robot_side in ("left", "right")
        }

        return {
            "schema": "inmoov.cv_ik.poc.v2",
            "timestamp_s": t,
            "robot": {
                "torso": {
                    "valid": torso_valid,
                    "yaw_rad": torso_yaw,
                    "bend_rad": torso_bend,
                    "source_lateral_lean_rad": self._f("torso.source_lateral_lean", raw_lateral_lean if basis_data is not None else 0.0, t) if torso_valid else 0.0,
                    "tracked_sagittal_lean_rad": torso_sagittal_lean,
                    "sagittal_lean_applied": False,
                    "sagittal_lean_reason": "Current maintained URDF topStom axis represents lateral lean; no matching sagittal forward/back torso DOF is exposed.",
                },
                "face": self._face_commands(face, torso_yaw, torso_bend, t),
                "arms": arms,
                "hands": hand_cmds,
                "legs": {
                    "applied": False,
                    "reason": "Uploaded model legs are explicitly treated as inaccurate in this proof-of-concept; pose is tracked but leg retargeting is disabled.",
                },
            },
            "collision": guard_status | {"physical_safety_certified": False},
            "tracking": {
                "face_valid": face.valid,
                "body_valid": body.valid,
                "left_hand_valid": hands["left"].valid,
                "right_hand_valid": hands["right"].valid,
                "body_joint_metrics_rad": body.joint_metrics_rad,
            },
        }
