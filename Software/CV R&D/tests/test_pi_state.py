import unittest

from inmoov_pi.state import RobotStateHub


class StateHubTests(unittest.TestCase):
    def test_default_state_is_truthfully_unverified(self):
        hub = RobotStateHub()
        snap = hub.snapshot()
        self.assertEqual(snap["schema"], "automaton.pi_state.v1")
        self.assertFalse(snap["safety"]["verified"])
        self.assertFalse(snap["safety"]["armed"])
        self.assertIn("ccb_supervisor", snap["control_nodes"])
        self.assertEqual(snap["control_nodes"]["head"]["status"], "unavailable")

    def test_perception_detail_keeps_full_payload(self):
        hub = RobotStateHub()
        perception = {
            "face": {"valid": True, "head_pose_rad": {"yaw": 0.1}, "eyelids_closed": {}, "gaze": {}},
            "body": {"valid": True},
            "hands": {"left": {"valid": True}, "right": {"valid": False}},
        }
        hub.update_perception(perception, {"timestamp_s": 1.0, "robot": {}, "simulation": {}},
                              fps=30.0, camera_id="aurora", monotonic_ns=100, unix_ns=200)
        detail = hub.perception_detail()
        self.assertEqual(detail["camera_id"], "aurora")
        self.assertEqual(detail["perception"]["face"]["head_pose_rad"]["yaw"], 0.1)
        self.assertTrue(hub.snapshot()["perception"]["hands"]["left"])


if __name__ == "__main__":
    unittest.main()
