import tempfile
import time
from pathlib import Path

import numpy as np

from aux_core.people import PersonStore
from aux_core.person_session import PersonSessionManager
from aux_core.state import AuxiliaryState


class DummyConversation:
    def clear_history(self, _reason):
        pass
    def history_size(self):
        return 0


class FlickerPi:
    def __init__(self):
        self.present = True
    def perception(self):
        return {"perception": {"face": {"valid": self.present}}}
    def frame(self, *args, **kwargs):
        return b"jpeg", {}


class NoIdentity:
    def available(self):
        return False
    def embedding_from_jpeg(self, _jpeg):
        return np.array([1.0, 0.0, 0.0], dtype=np.float32)


def test_brief_face_flicker_preserves_pending_name_prompt():
    with tempfile.TemporaryDirectory() as td:
        pi = FlickerPi()
        store = PersonStore({"database_path": "people.sqlite3"}, Path(td))
        mgr = PersonSessionManager(
            {
                "onboarding_enabled": True,
                "ask_name_after_turns": 0,
                "ask_name_retry_turns": 2,
                "leave_grace_s": 2.5,
            },
            pi, store, NoIdentity(), AuxiliaryState(),
            conversation=DummyConversation(),
        )

        first = mgr.process_user_text("Hi")
        assert first["action"] == "ask_name"
        assert mgr._awaiting_name is True

        # Simulate one bad/missed face frame, then immediate reacquisition.
        pi.present = False
        mgr._tick()
        assert mgr._face_present is False
        pi.present = True
        mgr._tick()

        # The pending onboarding state must survive the brief dropout so a bare
        # name such as "Jonathan" is interpreted as the answer to the prompt.
        learned = mgr.process_user_text("Jonathan")
        assert learned["action"] == "session_name_learned"
        assert learned["name"] == "Jonathan"
