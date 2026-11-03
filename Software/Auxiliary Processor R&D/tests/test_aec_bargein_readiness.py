from __future__ import annotations

import sys
import time
import types

import numpy as np

from aux_core.aec import EchoReferenceTimeline
from aux_core.audio_loop import AudioConversationLoop
from aux_core.audio_output import ContinuousWavPlayer


def _valid_metrics(**overrides):
    m = {
        "reference_present": True,
        "reference_coverage": 1.0,
        "aec_ready": True,
        "good_echo_age_ms": 100.0,
        "residual_rms": 0.02,
        "mic_rms": 0.05,
        "residual_to_mic_ratio": 0.40,
        "reference_correlation": 0.20,
        "erle_db": 3.0,
    }
    m.update(overrides)
    return m


def test_barge_gate_rejects_partial_reference_unready_and_stale_path():
    ok, why = AudioConversationLoop._barge_metrics_ok(
        _valid_metrics(reference_coverage=0.25), {}
    )
    assert not ok and why == "reference_gap"

    ok, why = AudioConversationLoop._barge_metrics_ok(
        _valid_metrics(aec_ready=False), {}
    )
    assert not ok and why == "aec_not_ready"

    ok, why = AudioConversationLoop._barge_metrics_ok(
        _valid_metrics(good_echo_age_ms=5000.0), {}
    )
    assert not ok and why == "echo_path_stale"

    ok, why = AudioConversationLoop._barge_metrics_ok(_valid_metrics(), {})
    assert ok and why == "double_talk_likely"


def test_reference_timeline_reports_time_coverage_independent_of_sample_amplitude():
    sr = 16000
    base = time.monotonic() + 0.1
    timeline = EchoReferenceTimeline(sr)
    # Silence is still a represented playback interval and should count as coverage.
    timeline.push(np.zeros(800, dtype=np.float32), sr, base)
    _samples, coverage = timeline.read_with_coverage(base, 400)
    assert coverage == 1.0
    _samples, coverage = timeline.read_with_coverage(base + 700 / sr, 400)
    assert 0.20 <= coverage <= 0.30


def test_continuous_player_cancel_is_cooperative_and_never_aborts_stream():
    player = ContinuousWavPlayer(first_preroll_ms=0)

    class FakeStream:
        def abort(self):
            raise AssertionError("cancel() must not abort PortAudio cross-thread")

        def stop(self):
            pass

        def close(self):
            pass

    fake = FakeStream()
    player._stream = fake
    player._rate = 16000
    player._channels = 1
    player.cancel()
    assert player._cancel_event.is_set()
    assert player._stream is fake


def test_reference_is_published_only_for_pcm_blocks_that_reach_playback(monkeypatch):
    arr = np.ones((1600, 1), dtype=np.float32) * 0.05  # 100 ms at 16 kHz
    fake_sf = types.SimpleNamespace(read=lambda *_a, **_k: (arr.copy(), 16000))
    monkeypatch.setitem(sys.modules, "soundfile", fake_sf)

    published = []
    player = ContinuousWavPlayer(
        first_preroll_ms=0,
        write_block_ms=20,
        on_reference=lambda block, rate, start: published.append((len(block), rate, start)),
    )
    player._continuous_available = True

    class FakeStream:
        latency = 0.0

        def __init__(self):
            self.writes = 0

        def write(self, _block):
            self.writes += 1
            # Simulate a barge-in arriving during the first playback block.
            if self.writes == 1:
                player.cancel()

        def stop(self):
            pass

        def close(self):
            pass

    fake = FakeStream()

    def ensure(rate, channels):
        player._stream = fake
        player._rate = rate
        player._channels = channels

    monkeypatch.setattr(player, "_ensure_stream", ensure)
    player.reset_cancel()
    player.play(b"not-a-real-wav")

    assert fake.writes == 1
    assert sum(n for n, _rate, _start in published) <= 320  # one 20 ms block
    assert sum(n for n, _rate, _start in published) < len(arr)


def test_aec_requires_fresh_current_utterance_echo_evidence():
    from aux_core.aec import AdaptiveEchoCanceller

    sr, n = 16000, 512
    t = np.arange(sr, dtype=np.float64) / sr
    far = (0.2 * np.sin(2 * np.pi * 220 * t) + 0.1 * np.sin(2 * np.pi * 510 * t)).astype(np.float32)
    base = time.monotonic() + 0.1
    timeline = EchoReferenceTimeline(sr)
    timeline.push(far, sr, base)
    aec = AdaptiveEchoCanceller(
        {
            "reference_delay_ms": 0,
            "delay_search_max_ms": 0,
            "adaptation_alpha": 0.70,
            "suppression": 0.98,
            "min_reference_rms": 1e-6,
            "adapt_min_correlation": 0.05,
            "ready_min_blocks": 3,
            "utterance_ready_min_blocks": 2,
            "ready_min_erle_db": 1.0,
        },
        timeline,
        sr,
    )
    metrics = None
    for i in range(0, n * 8, n):
        _residual, metrics = aec.process(0.6 * far[i:i+n], base + i / sr)
    assert metrics and metrics["aec_ready"] is True

    aec.begin_utterance()
    _residual, metrics = aec.process(0.6 * far[0:n], base)
    assert metrics["aec_ready"] is False
    _residual, metrics = aec.process(0.6 * far[n:2*n], base + n / sr)
    assert metrics["aec_ready"] is True
