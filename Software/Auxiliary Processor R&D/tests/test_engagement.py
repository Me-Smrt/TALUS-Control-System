import unittest
from aux_core.engagement import EngagementManager


class T(unittest.TestCase):
    def test_wake(self):
        e = EngagementManager({
            'enabled': True,
            'wake_phrases': ['hey robot'],
            'idle_accept_score': .7,
            'wake_score': 1,
            'active_window_s': 1,
        })
        self.assertTrue(e.evaluate('hey robot what time is it', {}, now=1)['accept'])

    def test_reject_background(self):
        e = EngagementManager({
            'enabled': True,
            'wake_phrases': ['hey robot'],
            'idle_accept_score': .7,
        })
        self.assertFalse(e.evaluate('I was talking to someone else', {}, now=1)['accept'])

    def test_actual_pi_gaze_payload_shape_can_contribute_to_engagement(self):
        cfg = {
            'enabled': True,
            'wake_phrases': [],
            'active_window_s': 25,
            'idle_accept_score': 0.7,
            'face_score': 0.18,
            'head_attention_score': 0.28,
            'gaze_attention_score': 0.36,
            'head_yaw_limit_deg': 28,
            'head_pitch_limit_deg': 24,
            'gaze_pan_limit': 0.35,
            'gaze_tilt_limit': 0.35,
        }
        mgr = EngagementManager(cfg)
        pi_state = {
            'perception': {
                'face': True,
                'head_pose_rad': {'yaw': 0.0, 'pitch': 0.0, 'roll': 0.0},
                'gaze': {'left': [0.1, -0.08], 'right': [0.12, -0.05]},
            }
        }
        result = mgr.evaluate('hello there', pi_state, now=100.0)
        self.assertTrue(result['accept'])
        self.assertIn('gaze_toward_robot', result['reason'])


if __name__ == '__main__':
    unittest.main()
