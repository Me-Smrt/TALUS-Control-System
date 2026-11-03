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
