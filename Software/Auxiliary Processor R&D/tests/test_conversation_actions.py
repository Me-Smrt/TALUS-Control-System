import unittest

from aux_core.conversation import ConversationManager


class CapturingLlm:
    def __init__(self):
        self.extra = None
    def chat(self, messages, image_jpeg=None, extra_prompt=None, reasoning_mode=None):
        self.extra = extra_prompt
        return "Okay."


class Pi:
    def frame(self, *args, **kwargs):
        return b"jpeg", {"X-Automaton-Camera": "aurora"}
    def choose_camera(self):
        return "aurora"


class Detector:
    def available(self):
        return False


class State:
    def update(self, *args, **kwargs):
        pass


class DummyPersonSession:
    def current_person(self):
        return None
    def process_user_text(self, text):
        return {
            "action": "ask_name",
            "ask_name": True,
            "prompt_context": "[Identity onboarding]\nBefore ending this reply, ask what the visible person would like to be called.",
        }
    def prompt_context(self):
        return "[Identity status]\nVisible person is not recognized."
    def maybe_remember(self, text):
        return None
    def note_turn_complete(self, onboarding, reply):
        pass
    def note_last_topic(self, user_text, reply_text):
        return None


class ConversationActionIntegrationV036Tests(unittest.TestCase):
    def test_implicit_scene_question_requests_camera(self):
        llm = CapturingLlm()
        c = ConversationManager(
            {
                "history_turns": 2,
                "visual_keywords": {"en": []},
                "visual_prompt": "use image",
                "action_router": {"enabled": True, "auto_vision": True},
            },
            llm, Pi(), Detector(), None, State(),
        )
        out = c.handle_text("Describe the room around you.", language="en")
        self.assertTrue(out["visual_used"])
        self.assertTrue(out["automatic_vision"])
        self.assertEqual(out["camera_id"], "aurora")

    def test_identity_onboarding_instruction_reaches_llm(self):
        llm = CapturingLlm()
        c = ConversationManager(
            {"history_turns": 2, "visual_keywords": {"en": []}, "visual_prompt": ""},
            llm, Pi(), Detector(), None, State(), person_session=DummyPersonSession(),
        )
        c.handle_text("Hi", language="en")
        self.assertIn("ask what the visible person would like to be called", llm.extra)


if __name__ == "__main__":
    unittest.main()
