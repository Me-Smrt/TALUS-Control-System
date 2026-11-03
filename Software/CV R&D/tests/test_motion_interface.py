import unittest

from inmoov_pi.motion_interface import IntentValidationError, validate_behavior_intent


class MotionIntentTests(unittest.TestCase):
    def test_high_level_intent_is_allowed(self):
        validate_behavior_intent({"intent": "look_at", "parameters": {"target_id": "person_1"}})

    def test_raw_servo_control_is_rejected(self):
        with self.assertRaises(IntentValidationError):
            validate_behavior_intent({"intent": "gesture", "parameters": {"servo_channel": 4, "position": 0.5}})


if __name__ == "__main__":
    unittest.main()
