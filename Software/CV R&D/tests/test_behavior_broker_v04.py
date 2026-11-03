import time
import unittest

from inmoov_pi.behavior import BehaviorBroker


class BehaviorBrokerTests(unittest.TestCase):
    def test_remote_monotonic_values_are_used_only_as_ttl_delta(self):
        broker = BehaviorBroker(planning_only=True, max_ttl_ms=5000)
        before = time.monotonic_ns()
        result = broker.submit({
            "intent": "look_at",
            "request_id": "clock-1",
            "issued_monotonic_ns": 100,
            "expires_monotonic_ns": 2_000_000_100,
            "parameters": {"target": "clock"},
        })
        after = time.monotonic_ns()
        self.assertGreaterEqual(result["received_monotonic_ns"], before)
        self.assertLessEqual(result["received_monotonic_ns"], after)
        ttl_ms = (result["expires_monotonic_ns"] - result["received_monotonic_ns"]) / 1_000_000
        self.assertAlmostEqual(ttl_ms, 2000, delta=2)

    def test_duplicate_request_id_is_idempotent(self):
        broker = BehaviorBroker(planning_only=True)
        payload = {
            "intent": "express",
            "request_id": "happy-1",
            "parameters": {"emotion": "happy", "intensity": 0.6},
        }
        a = broker.submit(payload)
        b = broker.submit(payload)
        self.assertEqual(a["received_monotonic_ns"], b["received_monotonic_ns"])


if __name__ == "__main__":
    unittest.main()
