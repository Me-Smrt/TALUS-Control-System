import json
import unittest
from unittest import mock

from aux_core.llm import OpenAICompatibleLlm


class _StreamResponse:
    def __init__(self, events):
        self.lines = [("data: " + json.dumps(e) + "\n").encode() for e in events] + [b"data: [DONE]\n"]
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def __iter__(self): return iter(self.lines)


class LlmContinuationTests(unittest.TestCase):
    def test_stream_auto_continues_after_length_finish(self):
        first = _StreamResponse([
            {"choices": [{"delta": {"content": "This is a long "}, "finish_reason": None}]},
            {"choices": [{"delta": {"content": "answer that "}, "finish_reason": None}]},
            {"choices": [{"delta": {}, "finish_reason": "length"}]},
        ])
        second = _StreamResponse([
            {"choices": [{"delta": {"content": "finishes cleanly."}, "finish_reason": None}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}]},
        ])
        llm = OpenAICompatibleLlm({
            "base_url": "http://127.0.0.1:8000/v1",
            "model": "test",
            "profiles": {"fast": {"max_tokens": 10, "auto_continue_on_length": 1}},
        })
        with mock.patch("aux_core.llm.urllib.request.urlopen", side_effect=[first, second]):
            text = "".join(llm.stream_chat([{"role": "user", "content": "test"}]))
        self.assertEqual(text, "This is a long answer that finishes cleanly.")


if __name__ == "__main__":
    unittest.main()
