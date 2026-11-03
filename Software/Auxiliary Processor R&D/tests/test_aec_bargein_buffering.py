from __future__ import annotations

import threading
import time

import numpy as np

from aux_core.aec import AdaptiveEchoCanceller, EchoReferenceTimeline
from aux_core.audio_loop import AudioConversationLoop
from aux_core.speech_stream import StreamingTtsPlayer


def test_streaming_tts_can_prebuffer_two_ready_chunks_before_first_play():
    first_synth_done = threading.Event()
    allow_second = threading.Event()
    playback_started = threading.Event()
    played = []

    def synth(text, language):
        if text == "one":
            first_synth_done.set()
        else:
            allow_second.wait(1.0)
        return text.encode()

    def play(wav):
        played.append(wav.decode())
        playback_started.set()

    p = StreamingTtsPlayer(
        synth,
        play,
        startup_buffer_chunks=2,
        startup_buffer_timeout_ms=1000,
    )
    p.submit("one")
    p.submit("two")
    assert first_synth_done.wait(0.5)
    # First audio is ready, but playback intentionally waits for the second.
    time.sleep(0.05)
    assert not playback_started.is_set()
    allow_second.set()
    assert playback_started.wait(0.5)
    p.wait()
    p.close()
    assert played == ["one", "two"]


def test_streaming_tts_short_reply_releases_when_submissions_finish():
    playback_started = threading.Event()

    p = StreamingTtsPlayer(
        lambda text, language: text.encode(),
        lambda wav: playback_started.set(),
        startup_buffer_chunks=2,
        startup_buffer_timeout_ms=1000,
    )
    p.submit("only chunk")
    time.sleep(0.05)
    assert not playback_started.is_set()
    p.finish_submissions()
    assert playback_started.wait(0.5)
    p.wait()
    p.close()


def test_aec_readiness_uses_verified_alignment_not_positive_erle_only():
    sr, n = 16000, 512
    rng = np.random.default_rng(4)
    far = rng.normal(0, 0.08, n * 10).astype(np.float32)
    base = time.monotonic() + 0.05
    timeline = EchoReferenceTimeline(sr)
    timeline.push(far, sr, base)
    aec = AdaptiveEchoCanceller(
        {
            "reference_delay_ms": 0,
            "delay_search_max_ms": 0,
            "adapt_min_correlation": 0.05,
            "ready_min_blocks": 3,
            "utterance_ready_min_blocks": 2,
            # Deliberately impossible ERLE requirement. Readiness should still
            # mean the reference path/alignment has been verified.
            "ready_min_erle_db": 99.0,
            "min_reference_rms": 1e-6,
        },
        timeline,
        sr,
    )
    metrics = None
    for i in range(0, n * 5, n):
        mic = 0.7 * far[i : i + n]
        _residual, metrics = aec.process(mic, base + i / sr)
    assert metrics is not None
    assert metrics["utterance_good_blocks"] >= 2
    assert metrics["aec_ready"] is True


def test_barge_gate_allows_strong_independent_near_end_before_erle_ready():
    metrics = {
        "reference_present": True,
        "reference_active": True,
        "reference_coverage": 1.0,
        "aec_ready": False,
        "adapted_blocks": 8,
        "good_echo_age_ms": 120.0,
        "residual_rms": 0.017,
        "mic_rms": 0.018,
        "reference_rms": 0.006,
        "residual_to_mic_ratio": 0.94,
        "reference_correlation": 0.04,
        "erle_db": 0.0,
    }
    ok, why = AudioConversationLoop._barge_metrics_ok(metrics, {})
    assert ok
    assert why == "strong_near_end_override"


def test_barge_gate_treats_covered_quiet_reference_as_pause_not_missing_reference():
    metrics = {
        "reference_present": True,
        "reference_active": False,
        "reference_coverage": 1.0,
        "aec_ready": True,
        "good_echo_age_ms": 100.0,
        "residual_rms": 0.012,
        "mic_rms": 0.012,
        "reference_rms": 0.0,
        "residual_to_mic_ratio": 1.0,
        "reference_correlation": 0.0,
        "erle_db": 0.0,
    }
    ok, why = AudioConversationLoop._barge_metrics_ok(metrics, {})
    assert ok
    assert why == "near_end_during_far_end_pause"
