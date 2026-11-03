from __future__ import annotations

import json
import unittest
from pathlib import Path

import numpy as np

from inmoov_cv.body import BodyState
from inmoov_cv.face import FaceState
from inmoov_cv.hands import HandState
from inmoov_cv.retarget import RobotRetargeter, mp_world_to_robot_camera, torso_basis

ROOT = Path(__file__).resolve().parents[1]


def synthetic_body() -> BodyState:
    pts = [[0.0, 0.0, 0.0] for _ in range(33)]
    # MediaPipe coordinates: x lateral, y down, z camera depth.
    pts[11] = [0.20, -0.30, 0.00]  # left shoulder -> robot [+.20, 0, +.30]
    pts[12] = [-0.20, -0.30, 0.00]
    pts[23] = [0.15, 0.00, 0.00]
    pts[24] = [-0.15, 0.00, 0.00]
    pts[13] = [0.35, -0.05, 0.00]
    pts[15] = [0.40, 0.20, -0.10]
    pts[14] = [-0.35, -0.05, 0.00]
    pts[16] = [-0.40, 0.20, -0.10]
    # lower-body filler
    pts[25] = [0.15, 0.40, 0.0]; pts[27] = [0.15, 0.80, 0.0]
    pts[26] = [-0.15, 0.40, 0.0]; pts[28] = [-0.15, 0.80, 0.0]
    norm = [[0.5, 0.5, 0.0] for _ in range(33)]
    return BodyState(True, norm, pts, [1.0] * 33, {})


class RetargetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads((ROOT / "config" / "default.json").read_text())

    def test_coordinate_mapping(self):
        result = mp_world_to_robot_camera(np.array([1.0, 2.0, 3.0]))
        np.testing.assert_allclose(result, [1.0, 3.0, -2.0])

    def test_frontal_torso_basis_is_identity_like(self):
        basis, yaw, bend, side_lean = torso_basis(synthetic_body())
        np.testing.assert_allclose(basis, np.eye(3), atol=1e-8)
        self.assertAlmostEqual(yaw, 0.0, places=8)
        self.assertAlmostEqual(bend, 0.0, places=8)
        self.assertAlmostEqual(side_lean, 0.0, places=8)

    def test_retarget_produces_bounded_arm_solution(self):
        retargeter = RobotRetargeter(self.config, ROOT / "config" / "inmoov_kinematics.json")
        hands = {"left": HandState(False), "right": HandState(False)}
        output = retargeter.retarget(1.0, FaceState(False), synthetic_body(), hands)
        self.assertTrue(output["robot"]["arms"]["left"]["valid"])
        self.assertTrue(output["robot"]["arms"]["right"]["valid"])
        for side in ("left", "right"):
            q = np.asarray(output["robot"]["arms"][side]["joint_angles_rad"])
            chain = retargeter.arms[side]
            self.assertTrue(np.all(q >= chain.lower - 1e-9))
            self.assertTrue(np.all(q <= chain.upper + 1e-9))

    def test_arm_schema_names_wrist_target_explicitly(self):
        retargeter = RobotRetargeter(self.config, ROOT / "config" / "inmoov_kinematics.json")
        hands = {"left": HandState(False), "right": HandState(False)}
        output = retargeter.retarget(1.0, FaceState(False), synthetic_body(), hands)
        for side in ("left", "right"):
            arm = output["robot"]["arms"][side]
            self.assertIn("wrist_target_from_shoulder_mm", arm)
            self.assertNotIn("target_from_shoulder_mm", arm)


    def test_wrist_commands_are_separate_from_arm_ik_and_use_symmetric_rotation_joint(self):
        cfg = json.loads((ROOT / "config" / "default.json").read_text())
        cfg["retarget"]["wrist_neutral_calibration_frames"] = 1
        retargeter = RobotRetargeter(cfg, ROOT / "config" / "inmoov_kinematics.json")
        hand = HandState(
            valid=True,
            curls={"thumb": 0.0, "index": 0.0, "middle": 0.0, "ring": 0.0, "pinky": 0.0},
            palm_basis=[[1.0,0.0,0.0],[0.0,1.0,0.0],[0.0,0.0,1.0]],
        )
        output = retargeter.retarget(1.0, FaceState(False), synthetic_body(), {"left": hand, "right": hand})
        for side in ("left", "right"):
            wrist = output["robot"]["hands"][side]["wrist"]
            self.assertTrue(wrist["valid"])
            self.assertEqual(wrist["rotation_joint_name"], f"{side}_wrist_z")
            limits = retargeter.kin["arms"][side]["wrist_rotation_z"]
            self.assertLess(limits["lower"], 0.0)
            self.assertGreater(limits["upper"], 0.0)

    def test_face_mapping_is_clamped_to_model_limits(self):
        retargeter = RobotRetargeter(self.config, ROOT / "config" / "inmoov_kinematics.json")
        hands = {"left": HandState(False), "right": HandState(False)}
        face = FaceState(
            valid=True,
            yaw_rad=99.0, pitch_rad=-99.0, roll_rad=99.0,
            left_eyelid_closed=1.0, right_eyelid_closed=1.0,
            left_gaze_x=1.0, left_gaze_y=1.0,
            right_gaze_x=-1.0, right_gaze_y=-1.0,
            jaw_open=1.0,
        )
        output = retargeter.retarget(1.0, face, BodyState(False), hands)
        cmd = output["robot"]["face"]
        kin = retargeter.kin
        self.assertLessEqual(cmd["head"]["turn_rad"], kin["head"]["turn"]["upper"] + 1e-9)
        self.assertGreaterEqual(cmd["head"]["nod_rad"], kin["head"]["nod"]["lower"] - 1e-9)
        self.assertLessEqual(cmd["head"]["tilt_rad"], kin["head"]["tilt"]["upper"] + 1e-9)
        self.assertLessEqual(cmd["jaw_rad"], kin["jaw"]["upper"] + 1e-9)


if __name__ == "__main__":
    unittest.main()
