import json
import tempfile
from pathlib import Path

from aux_core.tts import TtsManager
from aux_core.voices import VoiceRegistry


def make_tts(td):
    root = Path(td)
    voices_path = root / "voices.json"
    voices_path.write_text(json.dumps({
        "voices": [
            {"id": "english", "backend": "mock", "enabled": True, "languages": ["en"]},
            {"id": "spanish", "backend": "mock", "enabled": True, "languages": ["es"]},
        ],
        "fallback_language_voice": {"en": "english", "es": "spanish"},
    }), encoding="utf-8")
    registry = VoiceRegistry(voices_path, root / "state.json", "english")
    tts = TtsManager({
        "default_voice_id": "english",
        "backends": {"mock": {"type": "mock_tone"}},
        "language_routing": {"enabled": True, "min_confidence": 0.80},
    }, registry, root)
    return tts


def test_spanish_reply_overrides_english_input_hint():
    with tempfile.TemporaryDirectory() as td:
        tts = make_tts(td)
        _wav, voice = tts.synthesize(
            "¡Hola! Todo bien por aquí, gracias. ¿Qué hay de nuevo?",
            language="en",
        )
        assert voice["id"] == "spanish"


def test_english_reply_uses_default_voice():
    with tempfile.TemporaryDirectory() as td:
        tts = make_tts(td)
        _wav, voice = tts.synthesize("Hello! How are you doing today?", language=None)
        assert voice["id"] == "english"


def test_explicit_voice_selection_remains_locked_for_preview():
    with tempfile.TemporaryDirectory() as td:
        tts = make_tts(td)
        _wav, voice = tts.synthesize("¡Hola! ¿Cómo estás?", voice_id="english")
        assert voice["id"] == "english"
