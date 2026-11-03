import numpy as np

from aux_core.audio_loop import AudioConversationLoop
from aux_core.engagement import EngagementManager


def _loop():
    cfg = {
        "default_conversation_language": "en",
        "language_switch_min_confidence": 0.70,
        "wake_only_max_tokens": 2,
        "speech_gate": {
            "enabled": True,
            "min_duration_ms": 300,
            "min_rms": 0.0025,
            "max_no_speech_probability": 0.58,
            "min_avg_logprob": -1.25,
            "wake_only_min_language_confidence": 0.35,
        },
    }
    engagement = EngagementManager({
        "wake_name": "TALUS",
        "wake_name_aliases": ["talus", "talos", "telus"],
        "wake_name_prefixes": ["hey", "okay", "ok"],
        "allow_bare_wake_name": True,
    })
    return AudioConversationLoop(cfg, None, engagement, None, None, None, None, debug=True)


def _audio(seconds=0.7, amplitude=0.02):
    return np.full(int(16000 * seconds), amplitude, dtype=np.float32)


def test_low_confidence_wake_noise_is_rejected():
    loop = _loop()
    result = {
        "text": "TALUS Talus",
        "language": "ja",
        "language_probability": 0.29,
        "avg_logprob": -0.4,
        "no_speech_probability": 0.10,
    }
    ok, reason, _ = loop._speech_gate(_audio(), result, 16000)
    assert not ok
    assert reason == "suspicious_low_confidence_wake"


def test_realistic_short_wake_can_pass_gate():
    loop = _loop()
    result = {
        "text": "Hey Talus",
        "language": "en",
        "language_probability": 0.46,
        "avg_logprob": -0.4,
        "no_speech_probability": 0.10,
    }
    ok, reason, _ = loop._speech_gate(_audio(), result, 16000)
    assert ok
    assert reason == "speech_like"


def test_high_no_speech_probability_rejects_background_event():
    loop = _loop()
    result = {
        "text": "Talos",
        "language": "en",
        "language_probability": 0.95,
        "avg_logprob": -0.3,
        "no_speech_probability": 0.90,
    }
    ok, reason, _ = loop._speech_gate(_audio(), result, 16000)
    assert not ok
    assert reason == "whisper_no_speech"


def test_low_energy_event_is_rejected():
    loop = _loop()
    result = {
        "text": "Talos",
        "language": "en",
        "language_probability": 0.95,
        "avg_logprob": -0.3,
        "no_speech_probability": 0.10,
    }
    ok, reason, _ = loop._speech_gate(_audio(amplitude=0.0001), result, 16000)
    assert not ok
    assert reason == "low_energy"


def test_wake_only_turn_inherits_active_language():
    loop = _loop()
    wake = loop.engagement.wake_match("TALUS Talus")
    language, reason = loop._select_turn_language(
        {"language": "ja", "language_probability": 0.29},
        "TALUS Talus",
        wake=wake,
    )
    assert language == "en"
    assert reason == "wake_only_inherit"


def test_low_confidence_latin_switch_inherits_english():
    loop = _loop()
    language, reason = loop._select_turn_language(
        {"language": "vi", "language_probability": 0.42},
        "This is ordinary English speech",
        wake=None,
    )
    assert language == "en"
    assert reason == "low_confidence_inherit"


def test_strong_script_can_switch_even_when_whisper_confidence_is_low():
    loop = _loop()
    language, reason = loop._select_turn_language(
        {"language": "ja", "language_probability": 0.30},
        "こんにちは",
        wake=None,
    )
    assert language == "ja"
    assert reason == "strong_script"
