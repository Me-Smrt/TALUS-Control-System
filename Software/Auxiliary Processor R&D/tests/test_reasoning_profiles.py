import unittest
from aux_core.reasoning import ReasoningPolicy


class ReasoningV034Tests(unittest.TestCase):
    def test_complex_multi_part_prompt_auto_selects_deep(self):
        policy = ReasoningPolicy({"default_mode": "auto", "auto_min_chars": 120, "auto_score_threshold": 2.0})
        prompt = (
            "Compare two architectures for this robot, analyze the trade-offs, then design a migration plan. "
            "First consider latency; second consider safety; third consider memory. What could fail? How would you debug it?"
        )
        decision = policy.choose(prompt)
        self.assertEqual(decision.mode, "deep")
        self.assertGreaterEqual(decision.score, 2.0)


if __name__ == "__main__":
    unittest.main()
