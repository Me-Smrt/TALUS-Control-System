from __future__ import annotations

import unittest
import numpy as np

from inmoov_cv.hands import HandAnalyzer


class HandMathTests(unittest.TestCase):
    def test_straight_joint_has_near_zero_curl(self):
        points = np.zeros((21, 3), dtype=float)
        points[5] = [0.0, 0.0, 0.0]
        points[6] = [0.0, 1.0, 0.0]
        points[7] = [0.0, 2.0, 0.0]
        self.assertAlmostEqual(HandAnalyzer._curl_at(points, 5, 6, 7), 0.0, places=6)

    def test_right_angle_joint_registers_curl(self):
        points = np.zeros((21, 3), dtype=float)
        points[5] = [0.0, 0.0, 0.0]
        points[6] = [0.0, 1.0, 0.0]
        points[7] = [1.0, 1.0, 0.0]
        value = HandAnalyzer._curl_at(points, 5, 6, 7)
        self.assertGreater(value, 0.70)
        self.assertLess(value, 0.80)


if __name__ == "__main__":
    unittest.main()
