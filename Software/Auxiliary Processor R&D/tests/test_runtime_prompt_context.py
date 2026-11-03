import tempfile
import unittest
from pathlib import Path

from aux_core.llm import OpenAICompatibleLlm
from aux_core.prompt_context import build_runtime_system_context


class FakeTts:
    def list_voices(self):
        return [
            {
                "id": "kokoro_af_heart",
                "display_name": "Kokoro — Heart (US female)",
                "backend": "kokoro",
                "language": "en-US",
                "languages": ["en"],
                "available": True,
            },
            {
                "id": "piper_de_de_thorsten_medium",
                "display_name": "Piper — Thorsten (German male, medium)",
                "backend": "piper",
                "language": "de-DE",
                "languages": ["de"],
                "available": True,
            },
            {
                "id": "piper_ru_ru_denis_medium",
                "display_name": "Piper — Denis (Russian male, medium)",
                "backend": "piper",
                "language": "ru-RU",
                "languages": ["ru"],
                "available": False,
            },
        ]


class FakeVoices:
    active_id = "kokoro_af_heart"


class TestRuntimePromptContextV042(unittest.TestCase):
    def test_inventory_lists_only_available_voices(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "models/qwen").mkdir(parents=True)
            (root / "models/qwen/model.gguf").write_bytes(b"x")
            cfg = {
                "llm": {"managed_server": {"model_path": "models/qwen/model.gguf"}},
                "stt": {}, "vision": {"detector": {}}, "knowledge": {}, "identity": {},
            }
            text = build_runtime_system_context(root, cfg, tts=FakeTts(), voices=FakeVoices())
            self.assertIn("English: Kokoro", text)
            self.assertIn("German: Piper", text)
            self.assertNotIn("Russian male", text)

    def test_system_prompt_marker_is_replaced(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "system.txt").write_text(
                "You are TALUS.\n\n{{RUNTIME_CAPABILITIES}}\n\nStay grounded.",
                encoding="utf-8",
            )
            llm = OpenAICompatibleLlm(
                {
                    "base_url": "http://127.0.0.1:8000/v1",
                    "model": "test",
                    "system_prompt_file": "system.txt",
                },
                root,
                runtime_system_context="- Installed voice: Test Voice",
            )
            self.assertIn("Installed voice: Test Voice", llm.system_prompt)
            self.assertNotIn("{{RUNTIME_CAPABILITIES}}", llm.system_prompt)
            self.assertIn("Stay grounded.", llm.system_prompt)

    def test_runtime_context_appends_for_legacy_prompt_without_marker(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "system.txt").write_text("You are TALUS.", encoding="utf-8")
            llm = OpenAICompatibleLlm(
                {"system_prompt_file": "system.txt"},
                root,
                runtime_system_context="RUNTIME BLOCK",
            )
            self.assertTrue(llm.system_prompt.startswith("You are TALUS."))
            self.assertTrue(llm.system_prompt.endswith("RUNTIME BLOCK"))


if __name__ == "__main__":
    unittest.main()
