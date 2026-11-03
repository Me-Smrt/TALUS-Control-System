from __future__ import annotations

import json
import math
import unittest
from pathlib import Path

from inmoov_cv.simulation import SimulationMotionAdapter, TrapezoidLimiter

ROOT = Path(__file__).resolve().parents[1]


class SimulationProfileTests(unittest.TestCase):
    def test_limiter_respects_velocity_and_does_not_overshoot(self):
        lim = TrapezoidLimiter(0.0)
        lim.step(1.0, 0.0, 0.5, 2.0)
        last = 0.0
        for i in range(1, 201):
            t = i * 0.01
            x = lim.step(1.0, t, 0.5, 2.0)
            self.assertLessEqual(abs(x - last), 0.5 * 0.01 + 1e-8)
            self.assertLessEqual(x, 1.0 + 1e-9)
            last = x
        self.assertGreater(last, 0.8)

    def test_simulation_copy_does_not_modify_raw_robot_target(self):
        cfg = json.loads((ROOT / "config" / "default.json").read_text())
        adapter = SimulationMotionAdapter(cfg)
        raw = {
            "timestamp_s": 1.0,
            "robot": {
                "torso": {"valid": True, "yaw_rad": 1.0, "bend_rad": 0.2},
                "face": {"valid": False},
                "arms": {"left": {"valid": True, "joint_angles_rad": [1.0]}, "right": {"valid": False}},
                "hands": {},
            },
        }
        sim = adapter.adapt(raw)
        self.assertEqual(raw["robot"]["arms"]["left"]["joint_angles_rad"], [1.0])
        self.assertEqual(raw["robot"]["torso"]["yaw_rad"], 1.0)
        self.assertIn("target_joint_angles_rad", sim["arms"]["left"])


if __name__ == "__main__":
    unittest.main()
