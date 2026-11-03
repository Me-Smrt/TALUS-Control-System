import tempfile
import unittest
from pathlib import Path

from aux_core.llm import OpenAICompatibleLlm


class TestLlmSystemPromptV035(unittest.TestCase):
    def test_budget_is_folded_into_single_system_message(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "system.txt").write_text("You are TALUS.", encoding="utf-8")
            llm = OpenAICompatibleLlm(
                {
                    "base_url": "http://127.0.0.1:8000/v1",
                    "model": "test",
                    "system_prompt_file": "system.txt",
                    "profiles": {"fast": {"max_tokens": 1024, "reasoning_effort": "none"}},
                },
                root,
            )
            payload, _ = llm._payload([{"role": "user", "content": "Hello"}], reasoning_mode="fast")
            systems = [m for m in payload["messages"] if m.get("role") == "system"]
            self.assertEqual(len(systems), 1)
            self.assertIn("You are TALUS.", systems[0]["content"])
            self.assertIn("1024", systems[0]["content"])
            self.assertEqual(payload["messages"][-1]["content"], "Hello")


if __name__ == "__main__":
    unittest.main()
