import tempfile
import time
import unittest
from pathlib import Path

from aux_core.people import PersonStore
from aux_core.person_session import PersonSessionManager
from aux_core.state import AuxiliaryState


class DummyIdentity:
    def available(self):
        return False


class DummyConversation:
    def __init__(self):
        self.reasons = []
        self._n = 2
    def clear_history(self, reason):
        self.reasons.append(reason)
        self._n = 0
    def history_size(self):
        return self._n


class DummyEngagement:
    def __init__(self): self.reset_count = 0
    def reset(self): self.reset_count += 1


class DummyPi:
    def __init__(self): self.present = True
    def perception(self):
        return {"perception": {"face": {"valid": self.present}}}


class PersonSessionTests(unittest.TestCase):
    def test_face_leave_resets_conversation_without_identity_model(self):
        with tempfile.TemporaryDirectory() as td:
            pi = DummyPi(); conv = DummyConversation(); eng = DummyEngagement()
            store = PersonStore({"database_path": "people.sqlite3"}, Path(td))
            mgr = PersonSessionManager(
                {"leave_grace_s": 0.05, "poll_interval_s": 0.01},
                pi, store, DummyIdentity(), AuxiliaryState(), conversation=conv, engagement=eng,
            )
            mgr._tick()
            self.assertTrue(mgr.status()["face_present"])
            pi.present = False
            mgr._last_face_seen = time.monotonic() - 1.0
            mgr._tick()
            self.assertIn("person_left_frame", conv.reasons)
            self.assertEqual(eng.reset_count, 1)


if __name__ == "__main__":
    unittest.main()

class DummyMatchStore(PersonStore):
    pass

class DummyRecognitionIdentity:
    def __init__(self): self.vec = None
    def available(self): return True
    def embedding_from_jpeg(self, jpeg):
        import numpy as np
        return np.array(self.vec if self.vec is not None else [1.0, 0.0], dtype=np.float32)

class DummyPiFrame(DummyPi):
    def frame(self, *args, **kwargs): return b"jpeg", {}

class PersonIdentityChangeTests(unittest.TestCase):
    def test_repeated_unknown_face_clears_known_identity(self):
        import numpy as np
        with tempfile.TemporaryDirectory() as td:
            store = PersonStore({"database_path": "people.sqlite3"}, Path(td))
            known = store.register("Alice", np.array([1.0, 0.0], dtype=np.float32))
            pi = DummyPiFrame(); conv = DummyConversation(); eng = DummyEngagement(); ident = DummyRecognitionIdentity()
            mgr = PersonSessionManager(
                {"match_threshold": 0.8, "identity_confirmations": 1, "unknown_confirmations": 2},
                pi, store, ident, AuxiliaryState(), conversation=conv, engagement=eng,
            )
            ident.vec = [1.0, 0.0]
            mgr._recognize_once()
            self.assertEqual(mgr.current_person()["person_id"], known["person_id"])
            ident.vec = [0.0, 1.0]
            mgr._recognize_once()
            self.assertIsNotNone(mgr.current_person())
            mgr._recognize_once()
            self.assertIsNone(mgr.current_person())
            self.assertIn("person_identity_no_longer_matches", conv.reasons)
