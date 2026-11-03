import unittest

from aux_core.conversation import ConversationManager
from aux_core.state import AuxiliaryState


class Dummy:
    pass


class ConversationResetTests(unittest.TestCase):
    def test_clear_history_removes_all_context_and_public_last_turn(self):
        state = AuxiliaryState("test")
        conv = ConversationManager(
            {"history_turns": 4, "reasoning": {}},
            Dummy(), Dummy(), Dummy(), Dummy(), state,
        )
        conv.history.append({"role": "user", "content": "stale user"})
        conv.history.append({"role": "assistant", "content": "stale assistant"})
        state.update("conversation", last_user_text="stale user", last_reply_text="stale assistant")

        conv.clear_history("test_interrupt")

        self.assertEqual(conv.history_size(), 0)
        snap = state.snapshot()["conversation"]
        self.assertIsNone(snap["last_user_text"])
        self.assertIsNone(snap["last_reply_text"])
        self.assertEqual(snap["history_messages"], 0)
        self.assertEqual(snap["reset_reason"], "test_interrupt")


if __name__ == "__main__":
    unittest.main()

class EpochResetTests(unittest.TestCase):
    def test_inflight_turn_does_not_repopulate_history_after_reset(self):
        state = AuxiliaryState("test")

        class Llm:
            callback = None
            def stream_chat(self, messages, **kwargs):
                if self.callback:
                    self.callback()
                yield "answer"

        class Pi: pass
        class Detector:
            def available(self): return False

        llm = Llm()
        conv = ConversationManager(
            {"history_turns": 4, "reasoning": {}, "visual_keywords": {}},
            llm, Pi(), Detector(), None, state,
        )
        llm.callback = lambda: conv.clear_history("person_left_frame")
        out = conv.handle_text("hello", on_reply_delta=lambda _x: None)
        self.assertTrue(out["context_discarded"])
        self.assertEqual(conv.history_size(), 0)
