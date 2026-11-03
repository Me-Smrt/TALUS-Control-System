from __future__ import annotations

import json
import unittest
from pathlib import Path

import numpy as np

from inmoov_cv.kinematics import ArmChain, scaled_limb_targets

ROOT = Path(__file__).resolve().parents[1]


class KinematicsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = json.loads((ROOT / "config" / "inmoov_kinematics.json").read_text())

    def test_rest_lengths_are_physical(self):
        for side in ("left", "right"):
            chain = ArmChain(self.cfg["arms"][side])
            self.assertGreater(chain.rest_shoulder_to_elbow_m, 0.25)
            self.assertLess(chain.rest_shoulder_to_elbow_m, 0.50)
            self.assertGreater(chain.rest_elbow_to_wrist_m, 0.20)
            self.assertLess(chain.rest_elbow_to_wrist_m, 0.40)

    def test_solver_recovers_reachable_pose(self):
        for side in ("left", "right"):
            chain = ArmChain(self.cfg["arms"][side])
            desired_q = np.array([0.50, 0.30, 0.0, 0.70])
            _, elbow, wrist = chain.forward(desired_q)
            sol = chain.solve(elbow, wrist, elbow_weight=0.5, max_iterations=100)
            self.assertLess(sol.wrist_error_m, 0.002)
            self.assertLess(sol.elbow_error_m, 0.002)
            self.assertTrue(np.all(sol.q >= chain.lower - 1e-9))
            self.assertTrue(np.all(sol.q <= chain.upper + 1e-9))

    def test_human_vectors_are_rescaled_not_copied(self):
        elbow, wrist = scaled_limb_targets(
            np.array([0.0, 0.0, 0.0]),
            np.array([0.2, 0.0, -0.2]),
            np.array([0.4, 0.0, -0.4]),
            0.38,
            0.32,
        )
        self.assertAlmostEqual(np.linalg.norm(elbow), 0.38, places=8)
        self.assertAlmostEqual(np.linalg.norm(wrist - elbow), 0.32, places=8)


if __name__ == "__main__":
    unittest.main()
