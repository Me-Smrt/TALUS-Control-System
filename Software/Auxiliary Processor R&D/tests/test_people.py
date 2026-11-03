import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

from aux_core.people import PersonStore


class PeopleStoreTests(unittest.TestCase):
    def test_people_and_memory_caps(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = PersonStore({
                "database_path": "people.sqlite3",
                "max_people": 2,
                "max_memories_per_person": 2,
            }, root)
            a = store.register("Alice", np.array([1.0, 0.0, 0.0], dtype=np.float32))
            time.sleep(0.01)
            b = store.register("Bob", np.array([0.0, 1.0, 0.0], dtype=np.float32))
            time.sleep(0.01)
            c = store.register("Carol", np.array([0.0, 0.0, 1.0], dtype=np.float32))
            names = [x["name"] for x in store.list_people()]
            self.assertEqual(len(names), 2)
            self.assertNotIn("Alice", names)
            self.assertIn("Bob", names)
            self.assertIn("Carol", names)

            store.remember(c["person_id"], "one")
            store.remember(c["person_id"], "two")
            store.remember(c["person_id"], "three")
            self.assertEqual([x["text"] for x in store.memories(c["person_id"])], ["two", "three"])

    def test_cosine_match(self):
        with tempfile.TemporaryDirectory() as td:
            store = PersonStore({"database_path": "people.sqlite3"}, Path(td))
            p = store.register("Alice", np.array([1.0, 0.0], dtype=np.float32))
            match = store.match(np.array([0.99, 0.01], dtype=np.float32), 0.8)
            self.assertIsNotNone(match)
            self.assertEqual(match.person_id, p["person_id"])


if __name__ == "__main__":
    unittest.main()
