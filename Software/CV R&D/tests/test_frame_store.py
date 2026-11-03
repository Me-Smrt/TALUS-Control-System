import unittest
import numpy as np

from inmoov_pi.frame_store import LatestFrameStore


class FrameStoreTests(unittest.TestCase):
    def test_processed_can_fall_back_to_raw(self):
        store = LatestFrameStore()
        frame = np.zeros((20, 30, 3), dtype=np.uint8)
        store.publish_raw("eye", frame, sequence=4, monotonic_ns=10, unix_ns=20)
        item = store.get_jpeg("eye", "processed")
        self.assertIsNotNone(item)
        data, meta = item
        self.assertGreater(len(data), 10)
        self.assertEqual(meta.sequence, 4)
        self.assertEqual(meta.fallback_from, "raw")

    def test_processed_keeps_same_sequence(self):
        store = LatestFrameStore()
        raw = np.zeros((10, 10, 3), dtype=np.uint8)
        processed = np.ones((10, 10, 3), dtype=np.uint8) * 255
        store.publish_raw("aurora", raw, sequence=7, monotonic_ns=100, unix_ns=200)
        store.publish_processed("aurora", processed, sequence=7, monotonic_ns=100, unix_ns=200)
        _, meta = store.get_jpeg("aurora", "processed")
        self.assertEqual(meta.sequence, 7)
        self.assertIsNone(meta.fallback_from)


if __name__ == "__main__":
    unittest.main()
