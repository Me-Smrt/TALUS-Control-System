import io
import json
import tempfile
import unittest
import urllib.request
import wave
from pathlib import Path

from aux_core.api_server import AuxApiServer
from aux_core.state import AuxiliaryState
from aux_core.tts import TtsManager
from aux_core.voices import VoiceRegistry


class ConversationStub:
    def handle_text(self, *args, **kwargs):
        return {"reply": "ok"}

    def clear_history(self, *_args, **_kwargs):
        return None


class VoiceSetTests(unittest.TestCase):
    def _make(self, root: Path):
        data = {
            "default_voice_set_id": "female",
            "voices": [
                {"id": "en_f", "display_name": "English F", "backend": "mock", "languages": ["en"], "gender": "female", "enabled": True},
                {"id": "en_m", "display_name": "English M", "backend": "mock", "languages": ["en"], "gender": "male", "enabled": True},
                {"id": "fr_f", "display_name": "French F", "backend": "mock", "languages": ["fr"], "gender": "female", "enabled": True},
                {"id": "fr_m", "display_name": "French M", "backend": "mock", "languages": ["fr"], "gender": "male", "enabled": True},
                {"id": "ko_f", "display_name": "Korean F", "backend": "mock", "languages": ["ko"], "gender": "female", "enabled": True},
            ],
            "fallback_language_voice": {"en": "en_f", "fr": "fr_f", "ko": "ko_f"},
            "voice_sets": [
                {"id": "female", "display_name": "Female", "enabled": True, "fallback_policy": "strict", "selector": {"gender": "female"}, "language_voices": {"en": "en_f", "fr": "fr_f", "ko": "ko_f"}},
                {"id": "male", "display_name": "Male", "enabled": True, "fallback_policy": "strict", "selector": {"gender": "male"}, "language_voices": {"en": "en_m", "fr": "fr_m"}},
                {"id": "best_available", "display_name": "Best", "enabled": True, "fallback_policy": "correct_language", "selector": {}, "language_voices": {"en": "en_f", "fr": "fr_f", "ko": "ko_f"}},
            ],
        }
        path = root / "voices.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        registry = VoiceRegistry(path, root / "state.json", "en_f")
        tts = TtsManager({"backends": {"mock": {"type": "mock_tone"}}, "speed": 1.0}, registry, root)
        return registry, tts

    def test_default_and_persistence(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            registry, _ = self._make(root)
            self.assertEqual(registry.active_set_id, "female")
            registry.set_active_set("male")
            registry2 = VoiceRegistry(root / "voices.json", root / "state.json", "en_f")
            self.assertEqual(registry2.active_set_id, "male")
            self.assertEqual(registry2.active_id, "en_m")

    def test_strict_set_never_crosses_gender(self):
        from aux_core.tts import VoiceSetUnavailable

        with tempfile.TemporaryDirectory() as d:
            registry, tts = self._make(Path(d))
            registry.set_active_set("male")
            _, voice = tts.synthesize("hello", language="en")
            self.assertEqual(voice["id"], "en_m")
            _, voice = tts.synthesize("bonjour", language="fr")
            self.assertEqual(voice["id"], "fr_m")
            # Male has no Korean model. A strict set must not leak to ko_f.
            with self.assertRaises(VoiceSetUnavailable):
                tts.synthesize("안녕하세요", language="ko")

    def test_best_available_can_cross_gender_for_language_coverage(self):
        with tempfile.TemporaryDirectory() as d:
            registry, tts = self._make(Path(d))
            registry.set_active_set("best_available")
            _, voice = tts.synthesize("안녕하세요", language="ko")
            self.assertEqual(voice["id"], "ko_f")

    def test_voice_set_coverage(self):
        with tempfile.TemporaryDirectory() as d:
            _, tts = self._make(Path(d))
            sets = {row["id"]: row for row in tts.list_voice_sets()}
            self.assertEqual(sets["female"]["exact_language_count"], 3)
            self.assertEqual(sets["female"]["available_language_count"], 3)
            self.assertEqual(sets["male"]["exact_language_count"], 2)
            self.assertEqual(sets["male"]["available_language_count"], 2)
            self.assertEqual(sets["best_available"]["available_language_count"], 3)

    def test_api_selects_set_and_synthesizes_with_it(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            registry, tts = self._make(root)
            server = AuxApiServer(
                {"bind_host": "127.0.0.1", "port": 0, "allow_unauthenticated_loopback": True},
                AuxiliaryState(),
                tts,
                registry,
                ConversationStub(),
            )
            server.start()
            try:
                req = urllib.request.Request(
                    f"http://127.0.0.1:{server.port}/v1/voice-sets/select",
                    data=json.dumps({"voice_set_id": "male"}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req) as response:
                    payload = json.load(response)
                self.assertEqual(payload["active_voice_set_id"], "male")

                req = urllib.request.Request(
                    f"http://127.0.0.1:{server.port}/v1/tts/synthesize",
                    data=json.dumps({"text": "bonjour", "voice_set_id": "male", "language": "fr"}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req) as response:
                    self.assertEqual(response.headers.get("X-Automaton-Voice-Id"), "fr_m")
                    self.assertEqual(response.headers.get("X-Automaton-Voice-Set-Id"), "male")
                    body = response.read()
                with wave.open(io.BytesIO(body), "rb") as wav:
                    self.assertEqual(wav.getnchannels(), 1)
            finally:
                server.stop()


if __name__ == "__main__":
    unittest.main()
