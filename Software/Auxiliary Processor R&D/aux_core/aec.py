from __future__ import annotations

"""Lightweight acoustic echo cancellation primitives for TALUS.

This module intentionally has no new runtime dependency beyond NumPy.  It is a
first-stage, instrumented AEC backend for R&D and a stable interface for a later
WebRTC/Speex/OS-native backend on robot hardware.

The canceller receives the exact PCM sent to TALUS's speaker as a far-end
reference.  A timestamped reference timeline aligns that signal with microphone
blocks, then an adaptive frequency-domain transfer estimate subtracts the echo.
It is deliberately conservative: when alignment/reference confidence is poor,
it prefers *not* to declare a barge-in rather than muting legitimate audio.
"""

from collections import deque
import math
import threading
import time
from typing import Deque

import numpy as np


def _mono_float32(samples) -> np.ndarray:
    arr = np.asarray(samples, dtype=np.float32)
    if arr.ndim == 0:
        return arr.reshape(1)
    if arr.ndim > 1:
        arr = np.mean(arr, axis=1, dtype=np.float32)
    return np.ascontiguousarray(arr.reshape(-1), dtype=np.float32)


def _resample_linear(samples: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    samples = _mono_float32(samples)
    if source_rate <= 0 or target_rate <= 0 or samples.size == 0:
        return samples
    if int(source_rate) == int(target_rate):
        return samples.copy()
    n_out = max(1, int(round(samples.size * float(target_rate) / float(source_rate))))
    old_x = np.linspace(0.0, 1.0, samples.size, endpoint=False, dtype=np.float64)
    new_x = np.linspace(0.0, 1.0, n_out, endpoint=False, dtype=np.float64)
    return np.interp(new_x, old_x, samples).astype(np.float32)


class EchoReferenceTimeline:
    """Timestamped, thread-safe speaker reference at the microphone sample rate."""

    def __init__(self, sample_rate: int, *, retain_s: float = 8.0) -> None:
        self.sample_rate = int(sample_rate)
        self.retain_s = max(2.0, float(retain_s))
        self._segments: Deque[tuple[float, np.ndarray]] = deque()
        self._lock = threading.RLock()
        self.last_push_monotonic: float | None = None

    def push(self, samples, source_rate: int, start_monotonic: float | None = None) -> None:
        arr = _resample_linear(_mono_float32(samples), int(source_rate), self.sample_rate)
        if arr.size == 0:
            return
        start = float(start_monotonic if start_monotonic is not None else time.monotonic())
        with self._lock:
            self._segments.append((start, arr))
            self.last_push_monotonic = start
            self._prune_locked(time.monotonic())

    def _prune_locked(self, now: float) -> None:
        cutoff = float(now) - self.retain_s
        while self._segments:
            start, arr = self._segments[0]
            end = start + (arr.size / float(self.sample_rate))
            if end >= cutoff:
                break
            self._segments.popleft()

    def clear(self) -> None:
        with self._lock:
            self._segments.clear()
            self.last_push_monotonic = None

    def read_with_coverage(self, start_monotonic: float, frames: int) -> tuple[np.ndarray, float]:
        """Return aligned reference PCM plus timeline coverage fraction.

        Coverage describes whether the requested time range is represented by
        reference segments, independent of whether those samples happen to be
        quiet.  Barge-in must not treat a tiny edge of a TTS chunk as a valid
        full-block echo reference.
        """
        frames = max(0, int(frames))
        out = np.zeros(frames, dtype=np.float32)
        covered = np.zeros(frames, dtype=np.bool_)
        if frames == 0:
            return out, 0.0
        request_start = float(start_monotonic)
        request_end = request_start + frames / float(self.sample_rate)
        with self._lock:
            segments = list(self._segments)
        for seg_start, seg in segments:
            seg_end = seg_start + seg.size / float(self.sample_rate)
            if seg_end <= request_start or seg_start >= request_end:
                continue
            overlap_start = max(request_start, seg_start)
            overlap_end = min(request_end, seg_end)
            dst0 = int(round((overlap_start - request_start) * self.sample_rate))
            src0 = int(round((overlap_start - seg_start) * self.sample_rate))
            count = min(
                frames - dst0,
                seg.size - src0,
                max(0, int(round((overlap_end - overlap_start) * self.sample_rate))),
            )
            if count > 0:
                out[dst0 : dst0 + count] += seg[src0 : src0 + count]
                covered[dst0 : dst0 + count] = True
        return out, float(np.mean(covered)) if covered.size else 0.0

    def read(self, start_monotonic: float, frames: int) -> np.ndarray:
        out, _coverage = self.read_with_coverage(start_monotonic, frames)
        return out


class AdaptiveEchoCanceller:
    """Adaptive frequency-domain echo subtractor with coarse delay tracking.

    This is intentionally a conservative R&D backend, not a claim of parity
    with mature WebRTC AEC3.  The interface is designed so a native backend can
    replace it later without changing the rest of TALUS's barge-in pipeline.
    """

    def __init__(self, cfg: dict, reference: EchoReferenceTimeline, sample_rate: int) -> None:
        self.cfg = dict(cfg or {})
        self.reference = reference
        self.sample_rate = int(sample_rate)
        self.enabled = bool(self.cfg.get("enabled", True))
        self.delay_ms = float(self.cfg.get("reference_delay_ms", 45.0))
        self.search_max_ms = max(self.delay_ms, float(self.cfg.get("delay_search_max_ms", 220.0)))
        self.search_step_ms = max(2.0, float(self.cfg.get("delay_step_ms", 8.0)))
        self.delay_update_interval_s = max(0.1, float(self.cfg.get("delay_update_interval_ms", 500.0)) / 1000.0)
        self.adaptation_alpha = min(0.995, max(0.0, float(self.cfg.get("adaptation_alpha", 0.88))))
        self.suppression = min(1.25, max(0.0, float(self.cfg.get("suppression", 0.95))))
        self.min_reference_rms = max(1e-6, float(self.cfg.get("min_reference_rms", 0.001)))
        self.adapt_min_corr = min(0.99, max(0.0, float(self.cfg.get("adapt_min_correlation", 0.12))))
        self.max_filter_gain = max(0.5, float(self.cfg.get("max_filter_gain", 4.0)))
        self._last_delay_update = 0.0
        self._sxx = None
        self._sdx = None
        self._fft_size = None
        self._lock = threading.RLock()
        self.ready_min_blocks = max(1, int(self.cfg.get("ready_min_blocks", 6)))
        self.utterance_ready_min_blocks = max(1, int(self.cfg.get("utterance_ready_min_blocks", 3)))
        self.ready_min_erle_db = float(self.cfg.get("ready_min_erle_db", 1.5))
        self.ready_min_reference_coverage = float(self.cfg.get("ready_min_reference_coverage", 0.80))
        self._adapted_blocks = 0
        # "good" here means the current playback has supplied a well-covered,
        # correlated far-end block.  v0.6.1 tied readiness to positive ERLE,
        # which proved too strict in a real room: a useful reference/alignment
        # can exist before the lightweight spectral canceller shows >1.5 dB
        # suppression.  Keep ERLE as a quality metric, but arm from verified
        # alignment and use the double-talk gate to decide whether to interrupt.
        self._utterance_good_blocks = 0
        self._erle_ema = 0.0
        self._last_good_echo_monotonic: float | None = None
        self._last_reference_active_monotonic: float | None = None


    def begin_utterance(self) -> None:
        """Require fresh echo-path evidence for each new TALUS utterance.

        Learned filter spectra and coarse delay are retained across turns, but a
        barge-in is not trusted until the current playback has itself produced a
        few well-referenced, successfully-cancelled blocks.  This prevents stale
        convergence from a previous answer from authorizing a bad reference
        alignment in the next answer.
        """
        with self._lock:
            self._utterance_good_blocks = 0
            self._last_good_echo_monotonic = None

    @staticmethod
    def _rms(x: np.ndarray) -> float:
        if x.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(np.square(x), dtype=np.float64)))

    @staticmethod
    def _corr(a: np.ndarray, b: np.ndarray) -> float:
        if a.size == 0 or b.size == 0:
            return 0.0
        aa = a.astype(np.float64, copy=False)
        bb = b.astype(np.float64, copy=False)
        denom = math.sqrt(float(np.dot(aa, aa)) * float(np.dot(bb, bb))) + 1e-12
        if denom <= 1e-10:
            return 0.0
        return float(np.clip(np.dot(aa, bb) / denom, -1.0, 1.0))

    def _candidate_reference(self, block_start: float, frames: int, delay_ms: float) -> tuple[np.ndarray, float]:
        return self.reference.read_with_coverage(block_start - (float(delay_ms) / 1000.0), frames)

    def _update_delay(self, mic: np.ndarray, block_start: float) -> tuple[np.ndarray, float, float]:
        now = time.monotonic()
        current, current_coverage = self._candidate_reference(block_start, mic.size, self.delay_ms)
        current_corr = abs(self._corr(mic, current))
        if now - self._last_delay_update < self.delay_update_interval_s:
            return current, current_corr, current_coverage
        self._last_delay_update = now

        best_delay = self.delay_ms
        best_ref = current
        best_corr = current_corr
        best_coverage = current_coverage
        # Search coarsely.  Delay changes slowly, so this only runs a few times
        # per second and remains cheap at 16 kHz / 512-sample blocks.
        d = 0.0
        while d <= self.search_max_ms + 1e-6:
            ref, coverage = self._candidate_reference(block_start, mic.size, d)
            if self._rms(ref) >= self.min_reference_rms:
                corr = abs(self._corr(mic, ref))
                if corr > best_corr:
                    best_delay, best_ref, best_corr, best_coverage = d, ref, corr, coverage
            d += self.search_step_ms
        # Only move the delay estimate when the far-end signal is actually
        # visible in the microphone.  Otherwise keep the prior calibration.
        if best_corr >= self.adapt_min_corr:
            self.delay_ms = 0.7 * self.delay_ms + 0.3 * best_delay
            best_ref, best_coverage = self._candidate_reference(block_start, mic.size, self.delay_ms)
            best_corr = abs(self._corr(mic, best_ref))
        return best_ref, best_corr, best_coverage

    def _ensure_spectra(self, frames: int) -> None:
        bins = frames // 2 + 1
        if self._fft_size == frames and self._sxx is not None and len(self._sxx) == bins:
            return
        self._fft_size = frames
        self._sxx = np.full(bins, 1e-6, dtype=np.float64)
        self._sdx = np.zeros(bins, dtype=np.complex128)

    def process(self, mic_samples, block_start_monotonic: float) -> tuple[np.ndarray, dict]:
        mic = _mono_float32(mic_samples)
        if not self.enabled or mic.size == 0:
            return mic.copy(), {"enabled": False}
        with self._lock:
            ref, corr, coverage = self._update_delay(mic, float(block_start_monotonic))
            mic_rms = self._rms(mic)
            ref_rms = self._rms(ref)
            reference_active = bool(ref_rms >= self.min_reference_rms)
            represented = bool(coverage >= min(0.50, self.ready_min_reference_coverage))
            now = time.monotonic()
            if not reference_active:
                good_echo_age_ms = (
                    (now - self._last_good_echo_monotonic) * 1000.0
                    if self._last_good_echo_monotonic is not None
                    else None
                )
                ready = bool(
                    self._adapted_blocks >= self.ready_min_blocks
                    and self._utterance_good_blocks >= self.utterance_ready_min_blocks
                    and self._last_good_echo_monotonic is not None
                )
                return mic.copy(), {
                    "enabled": True,
                    # Coverage and energy are deliberately separate.  Natural
                    # pauses between words are still represented by the playback
                    # timeline even though their RMS is near zero.
                    "reference_present": represented,
                    "reference_active": False,
                    "delay_ms": round(self.delay_ms, 2),
                    "mic_rms": mic_rms,
                    "reference_rms": ref_rms,
                    "reference_coverage": coverage,
                    "residual_rms": mic_rms,
                    "residual_to_mic_ratio": 1.0,
                    "reference_correlation": corr,
                    "erle_db": 0.0,
                    "aec_ready": ready,
                    "adapted_blocks": self._adapted_blocks,
                    "utterance_good_blocks": self._utterance_good_blocks,
                    "good_echo_age_ms": good_echo_age_ms,
                }
            self._last_reference_active_monotonic = now

            self._ensure_spectra(mic.size)
            X = np.fft.rfft(ref.astype(np.float64, copy=False))
            D = np.fft.rfft(mic.astype(np.float64, copy=False))
            power_x = np.abs(X) ** 2

            # Update the acoustic transfer estimate only when there is evidence
            # that far-end audio is present in the microphone.  This protects the
            # filter from learning/cancelling a near-end human during double-talk.
            if corr >= self.adapt_min_corr and coverage >= self.ready_min_reference_coverage:
                a = self.adaptation_alpha
                self._sxx = a * self._sxx + (1.0 - a) * power_x
                self._sdx = a * self._sdx + (1.0 - a) * (D * np.conj(X))
                self._adapted_blocks += 1

            H = self._sdx / (self._sxx + 1e-9)
            mag = np.abs(H)
            over = mag > self.max_filter_gain
            if np.any(over):
                H = H.copy()
                H[over] *= self.max_filter_gain / (mag[over] + 1e-12)

            echo_spec = H * X
            residual_spec = D - self.suppression * echo_spec
            residual = np.fft.irfft(residual_spec, n=mic.size).astype(np.float32)
            # Keep pathological adaptation from exploding the signal.
            residual = np.nan_to_num(residual, nan=0.0, posinf=1.0, neginf=-1.0)
            residual = np.clip(residual, -1.0, 1.0)
            residual_rms = self._rms(residual)
            ratio = residual_rms / max(mic_rms, 1e-9)
            erle = 10.0 * math.log10((mic_rms * mic_rms + 1e-12) / (residual_rms * residual_rms + 1e-12))
            if corr >= self.adapt_min_corr and coverage >= self.ready_min_reference_coverage:
                self._erle_ema = 0.85 * self._erle_ema + 0.15 * erle
                self._utterance_good_blocks += 1
                self._last_good_echo_monotonic = time.monotonic()
            ready = bool(
                self._adapted_blocks >= self.ready_min_blocks
                and self._utterance_good_blocks >= self.utterance_ready_min_blocks
                and self._last_good_echo_monotonic is not None
            )
            good_echo_age_ms = (
                (time.monotonic() - self._last_good_echo_monotonic) * 1000.0
                if self._last_good_echo_monotonic is not None
                else None
            )
            return residual, {
                "enabled": True,
                "reference_present": True,
                "reference_active": True,
                "delay_ms": round(self.delay_ms, 2),
                "mic_rms": mic_rms,
                "reference_rms": ref_rms,
                "reference_coverage": coverage,
                "residual_rms": residual_rms,
                "residual_to_mic_ratio": ratio,
                "reference_correlation": corr,
                "erle_db": erle,
                "aec_ready": ready,
                "adapted_blocks": self._adapted_blocks,
                "utterance_good_blocks": self._utterance_good_blocks,
                "erle_ema_db": self._erle_ema,
                "good_echo_age_ms": good_echo_age_ms,
            }
