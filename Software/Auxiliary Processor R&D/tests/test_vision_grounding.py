import unittest

from aux_core.conversation import ConversationManager


class Pi:
    def frame(self, *args, **kwargs):
        return b"jpeg", {"X-Automaton-Camera": "aurora"}
    def choose_camera(self):
        return "aurora"


class BrokenDetector:
    def available(self):
        return True
    def detect_jpeg(self, image):
        raise RuntimeError("CUDA device unavailable")


class State:
    def update(self, *args, **kwargs):
        pass


class CapturingLlm:
    def __init__(self):
        self.extra = None
        self.image = None
    def chat(self, messages, image_jpeg=None, extra_prompt=None, reasoning_mode=None):
        self.extra = extra_prompt or ""
        self.image = image_jpeg
        return "I can inspect the supplied image directly."


class VisionGroundingV054Tests(unittest.TestCase):
    def test_detector_failure_does_not_turn_into_camera_failure(self):
        llm = CapturingLlm()
        conv = ConversationManager(
            {
                "history_turns": 2,
                "visual_keywords": {"en": ["what am i holding"]},
                "visual_prompt": "Use the supplied image.",
                "action_router": {"enabled": True, "auto_vision": True},
            },
            llm,
            Pi(),
            BrokenDetector(),
            None,
            State(),
        )
        out = conv.handle_text("what am I holding?", language="en")
        self.assertEqual(llm.image, b"jpeg")
        self.assertTrue(out["visual_used"])
        self.assertIn("camera frame is available", llm.extra.lower())
        self.assertNotIn("camera frame was unavailable", llm.extra.lower())
        self.assertNotIn("cuda device unavailable", llm.extra.lower())

    def test_requested_output_language_is_grounded_in_prompt(self):
        llm = CapturingLlm()
        conv = ConversationManager(
            {
                "history_turns": 2,
                "visual_keywords": {"en": []},
                "visual_prompt": "",
                "action_router": {"enabled": True, "auto_vision": False},
            },
            llm,
            Pi(),
            BrokenDetector(),
            None,
            State(),
        )
        out = conv.handle_text("And finally manderin.", language="en")
        self.assertIn("explicitly requested the response in zh", llm.extra.lower())
        self.assertEqual(out["language"], "zh")


if __name__ == "__main__":
    unittest.main()
