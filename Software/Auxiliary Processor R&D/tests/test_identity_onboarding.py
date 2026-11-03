import tempfile
import unittest
from pathlib import Path

import numpy as np

from aux_core.people import PersonStore
from aux_core.person_session import PersonSessionManager
from aux_core.state import AuxiliaryState


class DummyConversation:
    def __init__(self):
        self.reasons = []
        self._n = 0
    def clear_history(self, reason):
        self.reasons.append(reason)
        self._n = 0
    def history_size(self):
        return self._n


class DummyPi:
    def perception(self):
        return {"perception": {"face": {"valid": True}}}
    def frame(self, *args, **kwargs):
        return b"jpeg", {}


class DummyIdentity:
    def __init__(self, available=True):
        self._available = available
    def available(self):
        return self._available
    def embedding_from_jpeg(self, _jpeg):
        return np.array([1.0, 0.0, 0.0], dtype=np.float32)


class IdentityOnboardingV036Tests(unittest.TestCase):
    def make(self, td, available=True):
        store = PersonStore({"database_path": "people.sqlite3"}, Path(td))
        return PersonSessionManager(
            {
                "onboarding_enabled": True,
                "ask_name_after_turns": 0,
                "ask_name_retry_turns": 2,
                "offer_persistent_identity": True,
                "identity_confirmations": 1,
                "unknown_confirmations": 1,
                "enrollment_samples": 1,
            },
            DummyPi(), store, DummyIdentity(available), AuxiliaryState(),
            conversation=DummyConversation(),
        ), store

    def test_unknown_visible_person_prompts_for_name_naturally(self):
        with tempfile.TemporaryDirectory() as td:
            mgr, _store = self.make(td, available=False)
            out = mgr.process_user_text("Hi!")
            self.assertTrue(out["ask_name"])
            self.assertEqual(out["action"], "ask_name")

    def test_name_can_be_session_only_when_identity_backend_missing(self):
        with tempfile.TemporaryDirectory() as td:
            mgr, _store = self.make(td, available=False)
            first = mgr.process_user_text("Hi")
            mgr.note_turn_complete(first, "Hi! What should I call you?")
            learned = mgr.process_user_text("Taylor")
            self.assertEqual(learned["action"], "session_name_learned")
            self.assertNotIn("ask_remember", learned)
            self.assertIn("Taylor", mgr.prompt_context())

    def test_name_then_yes_auto_enrolls_without_slash_command(self):
        with tempfile.TemporaryDirectory() as td:
            mgr, store = self.make(td, available=True)
            first = mgr.process_user_text("Hello")
            self.assertEqual(first["action"], "ask_name")
            mgr.note_turn_complete(first, "Hello! What should I call you?")
            learned = mgr.process_user_text("Taylor")
            self.assertTrue(learned.get("ask_remember"))
            consent = mgr.process_user_text("Yes")
            self.assertEqual(consent["action"], "person_enrolled")
            self.assertTrue(consent["saved"])
            self.assertEqual(mgr.current_person()["name"], "Taylor")
            self.assertEqual(store.counts()["people"], 1)

    def test_explicit_remember_me_as_is_direct_consent(self):
        with tempfile.TemporaryDirectory() as td:
            mgr, _store = self.make(td, available=True)
            out = mgr.process_user_text("Remember me as Taylor")
            self.assertEqual(out["action"], "person_enrolled")
            self.assertEqual(mgr.current_person()["name"], "Taylor")


if __name__ == "__main__":
    unittest.main()
