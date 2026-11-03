import sqlite3
import tempfile
import unittest
from pathlib import Path

import numpy as np

from aux_core.people import PersonStore
from aux_core.person_session import _compact_topic


class TestPeopleLastTopicV035(unittest.TestCase):
    def test_last_topic_is_rolling_and_not_explicit_memory(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = PersonStore({"database_path": "people.sqlite3", "max_topic_chars": 180}, root)
            person = store.register("Taylor", np.array([1.0, 0.0, 0.0], dtype=np.float32))
            store.remember(person["person_id"], "Prefers concise answers")
            first = store.set_last_topic(person["person_id"], "Talking about the RUC")
            self.assertEqual(first["text"], "Talking about the RUC")
            store.set_last_topic(person["person_id"], "Talking about facial recognition")
            self.assertEqual(store.last_topic(person["person_id"])["text"], "Talking about facial recognition")
            self.assertEqual(len(store.memories(person["person_id"])), 1)

    def test_existing_people_db_is_migrated(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db = root / "people.sqlite3"
            con = sqlite3.connect(db)
            con.execute("CREATE TABLE people (person_id TEXT PRIMARY KEY, name TEXT NOT NULL, embedding BLOB NOT NULL, embedding_dim INTEGER NOT NULL, created_at REAL NOT NULL, last_seen REAL NOT NULL, seen_count INTEGER NOT NULL DEFAULT 0)")
            con.execute("CREATE TABLE memories (memory_id INTEGER PRIMARY KEY AUTOINCREMENT, person_id TEXT NOT NULL, text TEXT NOT NULL, created_at REAL NOT NULL)")
            con.commit(); con.close()
            PersonStore({"database_path": "people.sqlite3"}, root)
            con = sqlite3.connect(db)
            cols = {row[1] for row in con.execute("PRAGMA table_info(people)")}
            con.close()
            self.assertIn("last_topic", cols)
            self.assertIn("last_topic_at", cols)

    def test_compact_topic_is_lossy_and_bounded(self):
        topic = _compact_topic("What offices are in the RUC?", "Career Development is in room 328. More follows.", 120)
        self.assertIn("RUC", topic)
        self.assertIn("Career Development", topic)
        self.assertLessEqual(len(topic), 120)


if __name__ == "__main__":
    unittest.main()

class _FakeIdentity:
    def available(self): return False

class _FakeState:
    def update(self, *args, **kwargs): pass
    def snapshot(self): return {"people": {}}

class _FakeConversation:
    def __init__(self, n): self.n = n
    def history_size(self): return self.n
    def clear_history(self, reason): self.n = 0

class TestTopicPromptUseV035(unittest.TestCase):
    def test_topic_only_injected_when_direct_history_empty(self):
        from aux_core.person_session import PersonSessionManager
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = PersonStore({"database_path": "people.sqlite3"}, root)
            person = store.register("Taylor", np.array([1.0, 0.0], dtype=np.float32))
            store.set_last_topic(person["person_id"], "User topic: robotics architecture")
            conv = _FakeConversation(0)
            mgr = PersonSessionManager({}, object(), store, _FakeIdentity(), _FakeState(), conversation=conv)
            mgr._current_id = person["person_id"]
            mgr._current_name = person["name"]
            self.assertIn("robotics architecture", mgr.prompt_context())
            conv.n = 2
            self.assertNotIn("robotics architecture", mgr.prompt_context())
