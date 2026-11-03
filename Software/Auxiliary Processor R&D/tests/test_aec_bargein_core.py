from __future__ import annotations

import time

import numpy as np

from aux_core.aec import AdaptiveEchoCanceller, EchoReferenceTimeline
from aux_core.audio_loop import AudioConversationLoop


def _signals(sr=16000, seconds=2.0, seed=7):
    rng = np.random.default_rng(seed)
    t = np.arange(int(sr * seconds), dtype=np.float64) / sr
    far = (
        0.22 * np.sin(2 * np.pi * 180 * t)
        + 0.14 * np.sin(2 * np.pi * 410 * t)
        + 0.025 * rng.standard_normal(t.size)
    ).astype(np.float32)
    near = (
        0.09 * np.sin(2 * np.pi * 760 * t)
        + 0.025 * rng.standard_normal(t.size)
    ).astype(np.float32)
    return far, near


def _aec(reference, sr=16000):
    return AdaptiveEchoCanceller(
        {
            "enabled": True,
            "reference_delay_ms": 0,
            "delay_search_max_ms": 0,
            "adaptation_alpha": 0.78,
            "suppression": 0.98,
            "min_reference_rms": 1e-5,
            "adapt_min_correlation": 0.05,
        },
        reference,
        sr,
    )


def test_reference_timeline_returns_aligned_pcm():
    sr = 16000
    base = time.monotonic() + 0.1
    src = np.linspace(-0.5, 0.5, 1600, dtype=np.float32)
    timeline = EchoReferenceTimeline(sr)
    timeline.push(src, sr, base)
    got = timeline.read(base + 400 / sr, 300)
    assert np.allclose(got, src[400:700], atol=1e-6)


def test_adaptive_aec_reduces_pure_far_end_echo():
    sr, n = 16000, 512
    far, _near = _signals(sr)
    base = time.monotonic() + 0.1
    timeline = EchoReferenceTimeline(sr)
    timeline.push(far, sr, base)
    aec = _aec(timeline, sr)

    ratios = []
    for i in range(0, len(far) - n + 1, n):
        mic = (0.65 * far[i : i + n]).astype(np.float32)
        residual, metrics = aec.process(mic, base + i / sr)
        if i >= sr // 2:
            ratios.append(float(np.sqrt(np.mean(residual**2))) / max(float(np.sqrt(np.mean(mic**2))), 1e-9))
    assert ratios
    assert np.mean(ratios) < 0.15
    assert metrics["reference_present"] is True


def test_adaptive_aec_preserves_near_end_during_double_talk():
    sr, n = 16000, 512
    far, near = _signals(sr)
    base = time.monotonic() + 0.1
    timeline = EchoReferenceTimeline(sr)
    timeline.push(far, sr, base)
    aec = _aec(timeline, sr)

    # Give the filter one second of far-end-only audio to learn the room path.
    for i in range(0, sr, n):
        aec.process((0.65 * far[i : i + n]).astype(np.float32), base + i / sr)

    correlations = []
    last_metrics = None
    for i in range(sr, len(far) - n + 1, n):
        target = near[i : i + n]
        mic = (0.65 * far[i : i + n] + target).astype(np.float32)
        residual, last_metrics = aec.process(mic, base + i / sr)
        correlations.append(float(np.corrcoef(residual, target)[0, 1]))
    assert np.mean(correlations) > 0.85
    assert last_metrics["residual_to_mic_ratio"] > 0.25


def test_barge_gate_requires_reference_and_converged_residual():
    cfg = {
        "min_residual_rms": 0.004,
        "min_residual_to_mic_ratio": 0.22,
        "min_erle_db": 2.0,
        "near_end_low_correlation_override": 0.35,
        "max_echo_only_correlation": 0.94,
        "high_corr_min_residual_ratio": 0.50,
    }
    ok, why = AudioConversationLoop._barge_metrics_ok({"reference_present": False}, cfg)
    assert not ok and why == "no_reference"

    ok, why = AudioConversationLoop._barge_metrics_ok(
        {
            "reference_present": True,
            "reference_coverage": 1.0,
            "aec_ready": True,
            "good_echo_age_ms": 120.0,
            "residual_rms": 0.03,
            "mic_rms": 0.08,
            "residual_to_mic_ratio": 0.38,
            "reference_correlation": 0.70,
            "erle_db": 4.5,
        },
        cfg,
    )
    assert ok and why == "double_talk_likely"
