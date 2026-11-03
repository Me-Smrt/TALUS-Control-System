from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from aux_core.audio_loop import AudioConversationLoop
from aux_core.engagement import EngagementManager


def _loop_cfg():
    return {
        "min_speech_ms": 250,
        "speech_gate": {
            "enabled": True,
            "min_duration_ms": 250,
            "min_rms": 0.0025,
            "max_no_speech_probability": 0.58,
            "min_avg_logprob": -1.25,
            "wake_only_min_language_confidence": 0.35,
        },
        "aec": {"barge_in": {}},
    }


def _loop():
    obj = AudioConversationLoop.__new__(AudioConversationLoop)
    obj.cfg = _loop_cfg()
    obj.engagement = EngagementManager({
        "wake_name": "TALUS",
        "wake_name_aliases": ["talus", "talos", "telus", "talous", "talis", "thales", "ataluz"],
        "wake_name_prefixes": ["hey", "okay", "ok"],
        "wake_phrases": ["hey robot", "okay robot", "ok robot"],
        "allow_bare_wake_name": True,
    })
    return obj


def test_barge_gate_rejects_unstable_residual_amplification_from_fan_case():
    # Exact signature from the v0.6.2 false barge-in: the synthetic residual
    # became >22x louder than the raw microphone input.
    metrics = {
        "reference_present": True,
        "reference_active": True,
        "reference_coverage": 1.0,
        "aec_ready": True,
        "good_echo_age_ms": 578.0,
        "residual_rms": 0.0054,
        "mic_rms": 0.0002,
        "reference_rms": 0.0568,
        "residual_to_mic_ratio": 22.66,
        "reference_correlation": 0.04,
        "erle_db": -27.1,
    }
    ok, why = AudioConversationLoop._barge_metrics_ok(metrics, {})
    assert not ok
    assert why in {"mic_too_quiet", "residual_unstable", "far_end_overwhelms_mic"}


def test_barge_gate_keeps_observed_real_double_talk_shape_valid():
    # Real successful interruption from the user's v0.6.2 test.
    metrics = {
        "reference_present": True,
        "reference_active": True,
        "reference_coverage": 1.0,
        "aec_ready": True,
        "good_echo_age_ms": 32.0,
        "residual_rms": 0.0084,
        "mic_rms": 0.0067,
        "reference_rms": 0.0214,
        "residual_to_mic_ratio": 1.26,
        "reference_correlation": 0.03,
        "erle_db": -2.0,
    }
    ok, why = AudioConversationLoop._barge_metrics_ok(metrics, {})
    assert ok, why


def test_barge_post_stt_gate_rejects_low_energy_hallucinated_wake():
    loop = _loop()
    audio = np.full(16000, 0.0030, dtype=np.float32)
    result = {
        "text": "TALUS Talus Telus",
        "language": "en",
        "language_probability": 0.98,
        "no_speech_probability": 0.0,
        "avg_logprob": -0.67,
    }
    meta = {"aec": {"mic_rms": 0.0002, "residual_to_mic_ratio": 22.66}}
    ok, why, _ = loop._barge_post_stt_gate(audio, result, 16000, meta)
    assert not ok
    assert why in {"barge_low_energy", "barge_trigger_mic_too_quiet", "barge_trigger_residual_unstable"}


def test_wake_only_repeated_aliases_are_attention_not_content():
    loop = _loop()
    wake = {"matched": True, "kind": "wake_name_bare", "raw_alias": "talus", "canonical": "TALUS"}
    assert loop._is_wake_only_text("TALUS Talus Telus", wake)
    assert loop._is_wake_only_text("Hey Talus", wake)
    assert not loop._is_wake_only_text("Talus explain that again", wake)
