import tempfile
from pathlib import Path

import numpy as np

from aux_core.people import PersonStore
from aux_core.person_session import PersonSessionManager
from aux_core.state import AuxiliaryState


class DummyConversation:
    def __init__(self):
        self.reasons = []
    def clear_history(self, reason):
        self.reasons.append(reason)
    def history_size(self):
        return 0


class DummyPi:
    def perception(self):
        return {"perception": {"face": {"valid": True}}}
    def frame(self, *args, **kwargs):
        return b"jpeg", {}


class DummyIdentity:
    def available(self):
        return True
    def embedding_from_jpeg(self, _jpeg):
        return np.array([1.0, 0.0, 0.0], dtype=np.float32)


def make_manager(td):
    store = PersonStore({"database_path": "people.sqlite3"}, Path(td))
    mgr = PersonSessionManager(
        {
            "onboarding_enabled": True,
            "ask_name_after_turns": 0,
            "ask_name_retry_turns": 2,
            "offer_persistent_identity": True,
            "identity_confirmations": 1,
            "unknown_confirmations": 1,
            "enrollment_samples": 1,
        },
        DummyPi(), store, DummyIdentity(), AuxiliaryState(),
        conversation=DummyConversation(),
    )
    return mgr, store


def test_conversational_affirmative_enrolls_person():
    with tempfile.TemporaryDirectory() as td:
        mgr, store = make_manager(td)
        first = mgr.process_user_text("Hello")
        mgr.note_turn_complete(first, "Hi! What should I call you?")
        learned = mgr.process_user_text("You can call me Tyler.")
        assert learned["action"] == "session_name_learned"
        assert learned.get("ask_remember") is True
        consent = mgr.process_user_text(
            "Sure! Sounds good to me. I'm about to start some ECE homework."
        )
        assert consent["action"] == "person_enrolled"
        assert consent["saved"] is True
        assert mgr.current_person()["name"] == "Tyler"
        assert store.counts()["people"] == 1


def test_session_name_does_not_fall_back_into_repeated_name_prompt():
    with tempfile.TemporaryDirectory() as td:
        mgr, _ = make_manager(td)
        first = mgr.process_user_text("Hello")
        mgr.note_turn_complete(first, "What should I call you?")
        learned = mgr.process_user_text("Tyler")
        assert learned["action"] == "session_name_learned"
        # Ambiguous/non-consent response: retain temporary name, don't nag.
        next_turn = mgr.process_user_text("I'm going to work on homework for a while.")
        assert next_turn["action"] == "session_name"
        later = mgr.process_user_text("Can you explain a circuit concept?")
        assert later["action"] == "session_name"
        assert "ask_name" not in later
