import unittest

from aux_core.conversation import ConversationManager
from aux_core.output_guard import clean_visible_answer


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


class LeakyVisionLlm:
    def __init__(self):
        self.stream_called = False

    def chat(self, messages, image_jpeg=None, extra_prompt=None, reasoning_mode=None):
        assert image_jpeg == b"jpeg"
        return (
            "It looks like a purple pen.\n</think>\n\n"
            "It looks like a purple pen."
        )

    def stream_chat(self, *args, **kwargs):
        self.stream_called = True
        yield "should never stream"


class OutputGuardV053Tests(unittest.TestCase):
    def test_orphan_closing_think_prefers_final_tail(self):
        text = "draft answer\n</think>\nfinal answer"
        self.assertEqual(clean_visible_answer(text), "final answer")

    def test_well_formed_think_block_is_removed(self):
        self.assertEqual(
            clean_visible_answer("<think>private scratch</think>Visible answer"),
            "Visible answer",
        )

    def test_visual_fast_turn_buffers_and_cleans_before_callback(self):
        llm = LeakyVisionLlm()
        conv = ConversationManager(
            {
                "history_turns": 2,
                "visual_keywords": {"en": ["what am i holding"]},
                "visual_prompt": "Use the supplied image.",
                "action_router": {"enabled": True, "auto_vision": True},
            },
            llm,
            Pi(),
            Detector(),
            None,
            State(),
        )
        deltas = []
        out = conv.handle_text("what am I holding?", language="en", on_reply_delta=deltas.append)
        self.assertEqual(out["reply"], "It looks like a purple pen.")
        self.assertEqual(deltas, ["It looks like a purple pen."])
        self.assertFalse(llm.stream_called)


if __name__ == "__main__":
    unittest.main()
