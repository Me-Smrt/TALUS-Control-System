"""Regression tests for camera-dependent answers and safe perception failures."""

import unittest
from unittest.mock import patch

from aux_core.action_router import InteractionActionRouter
from aux_core.conversation import ConversationManager


class DummyState:
    def update(self, *args, **kwargs):
        pass


class DummyDetector:
    def available(self):
        return False


class TrackingLlm:
    def __init__(self):
        self.calls = []

    def chat(self, messages, image_jpeg=None, extra_prompt=None, reasoning_mode=None):
        self.calls.append({"image": image_jpeg, "prompt": extra_prompt})
        return "I can see a binary number on your hand."


class FakePi:
    def __init__(self, *, available=True):
        self.available = available
        self.frame_calls = 0
        self.behavior_calls = 0

    def choose_camera(self):
        return "aurora"

    def frame(self, *args, **kwargs):
        self.frame_calls += 1
        if not self.available:
            raise ConnectionError("camera unavailable")
        return b"jpeg", {"X-Automaton-Camera": "aurora"}

    def observe(self, *args, **kwargs):
        raise ConnectionError("temporal camera unavailable")

    def submit_behavior(self, *args, **kwargs):
        self.behavior_calls += 1
        return {"status": "planning_only", "executed": False}


class VisualGroundingTests(unittest.TestCase):
    @staticmethod
    def make_conversation(pi=None, llm=None):
        pi = pi or FakePi()
        llm = llm or TrackingLlm()
        return ConversationManager(
            {
                "history_turns": 2,
                "visual_keywords": {"en": []},
                "visual_prompt": "Only describe the supplied image.",
                "action_router": {"enabled": True, "auto_vision": True},
            },
            llm, pi, DummyDetector(), None, DummyState(),
        ), pi, llm

    def test_previous_binary_hand_hallucination_prompts_camera(self):
        conv, pi, llm = self.make_conversation()
        out = conv.handle_text(
            "Can you tell me what this number is that I'm showing on my hand in binary?",
            language="en",
        )
        self.assertEqual(pi.frame_calls, 1)
        self.assertTrue(out["visual_used"])
        self.assertEqual(out["visual_grounding"]["status"], "CURRENT_IMAGE")
        self.assertEqual(out["visual_grounding"]["frame_count"], 1)
        self.assertIsNotNone(out["visual_grounding"]["received_at_utc"])
        self.assertIn("status=CURRENT_IMAGE", llm.calls[0]["prompt"])
        self.assertEqual(llm.calls[0]["image"], b"jpeg")

    def test_visual_reference_variants_route_to_camera(self):
        router = InteractionActionRouter({"enabled": True, "auto_vision": True})
        for request in (
            "What number am I showing you?",
            "Which hand am I using?",
            "Where am I pointing?",
            "What do I have in my hand?",
            "Can you tell what I'm holding?",
        ):
            with self.subTest(request=request):
                self.assertTrue(router.route(request, language="en").use_vision)

    def test_non_visual_concept_does_not_force_a_camera(self):
        router = InteractionActionRouter({"enabled": True, "auto_vision": True})
        self.assertFalse(router.route("How do binary numbers work?", language="en").use_vision)

    def test_camera_failure_never_invokes_llm_to_guess(self):
        conv, pi, llm = self.make_conversation(pi=FakePi(available=False))
        deltas = []
        out = conv.handle_text("What am I holding?", language="en", on_reply_delta=deltas.append)
        self.assertEqual(pi.frame_calls, 1)
        self.assertEqual(llm.calls, [])
        self.assertEqual(out["visual_grounding"]["status"], "UNAVAILABLE")
        self.assertFalse(out["visual_used"])
        self.assertIn("can't verify", out["reply"])
        self.assertEqual("".join(deltas), out["reply"])

    def test_motion_query_with_only_static_fallback_never_guesses_motion(self):
        conv, pi, llm = self.make_conversation()
        out = conv.handle_text("What am I doing right now?", language="en")
        self.assertEqual(pi.frame_calls, 1)
        self.assertEqual(llm.calls, [])
        self.assertEqual(out["visual_grounding"]["status"], "STATIC_ONLY")
        self.assertTrue(out["visual_used"])
        self.assertFalse(out["temporal_observation"])
        self.assertIn("sequence", out["reply"])

    def test_one_temporal_sample_does_not_count_as_motion_evidence(self):
        conv, pi, llm = self.make_conversation()
        pi.observe = lambda *args, **kwargs: {
            "manifest": {"camera_id": "aurora", "frames": [{"time_ms": 0}]},
            "frames": [b"jpeg"],
        }
        with patch("aux_core.conversation.build_contact_sheet", return_value=b"contact-sheet"):
            out = conv.handle_text("What am I doing right now?", language="en")
        self.assertEqual(out["visual_grounding"]["status"], "STATIC_ONLY")
        self.assertEqual(out["visual_grounding"]["frame_count"], 1)
        self.assertFalse(out["temporal_observation"])
        self.assertEqual(llm.calls, [])

    def test_no_spatial_behavior_submitted_without_camera(self):
        conv, pi, llm = self.make_conversation(pi=FakePi(available=False))
        out = conv.handle_text("Point at the cup", language="en")
        self.assertEqual(pi.behavior_calls, 0)
        self.assertEqual(llm.calls, [])
        self.assertEqual(out["behavior_result"]["status"], "rejected_no_observation")


if __name__ == "__main__":
    unittest.main()
