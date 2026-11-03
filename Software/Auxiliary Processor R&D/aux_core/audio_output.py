from __future__ import annotations

import io
import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path


def play_wav_bytes(wav: bytes, *, output_device=None) -> None:
    """Play WAV bytes and block until playback completes.

    This remains the simple one-shot helper for previews and non-streamed TTS.
    Streaming conversation uses ContinuousWavPlayer below so the output device
    stays open across chunks.
    """
    if os.name == "nt":
        import winsound

        winsound.PlaySound(wav, winsound.SND_MEMORY)
        return

    try:
        import soundfile as sf
        import sounddevice as sd

        arr, rate = sf.read(io.BytesIO(wav), dtype="float32")
        sd.play(arr, rate, device=output_device)
        sd.wait()
        return
    except Exception:
        pass

    player = shutil.which("afplay") or shutil.which("aplay") or shutil.which("paplay")
    if not player:
        raise RuntimeError(
            "No WAV playback backend found (sounddevice/soundfile, afplay, aplay, or paplay)."
        )
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(wav)
        path = Path(tmp.name)
    try:
        proc = subprocess.run([player, str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode(errors="ignore")[-1000:])
    finally:
        path.unlink(missing_ok=True)


class ContinuousWavPlayer:
    """Keep one sounddevice output stream open across synthesized chunks.

    v0.6.1 uses cooperative cancellation rather than aborting/closing PortAudio
    from the microphone thread.  Audio is written in small blocks, so cancel()
    only needs to set an Event; the playback worker notices it within one block
    and returns from stream.write() on its own thread.  This avoids a native
    sounddevice/PortAudio race that can terminate Python without a traceback.

    The AEC reference is published block-by-block immediately before the same
    PCM is written to the output device.  If speech is interrupted, reference
    audio that was never actually played is therefore never added to the echo
    timeline.
    """

    def __init__(
        self,
        *,
        output_device=None,
        trim_silence: bool = True,
        leading_silence_ms: float = 20.0,
        trailing_silence_ms: float = 70.0,
        silence_threshold: float = 0.0025,
        first_preroll_ms: float = 180.0,
        write_block_ms: float = 20.0,
        on_reference=None,
    ) -> None:
        self.output_device = output_device
        self.trim_silence = bool(trim_silence)
        self.leading_silence_ms = max(0.0, float(leading_silence_ms))
        self.trailing_silence_ms = max(0.0, float(trailing_silence_ms))
        self.silence_threshold = max(0.0, float(silence_threshold))
        self.first_preroll_ms = max(0.0, float(first_preroll_ms))
        self.write_block_ms = max(5.0, min(100.0, float(write_block_ms)))
        self.on_reference = on_reference
        self._needs_preroll = True
        self._stream = None
        self._rate = None
        self._channels = None
        self._lock = threading.RLock()
        self._cancel_event = threading.Event()
        self._reference_next_start = None
        try:
            import sounddevice as sd  # noqa: F401
            import soundfile as sf  # noqa: F401

            self._continuous_available = True
        except Exception:
            self._continuous_available = False

    def _trim(self, arr, rate):
        if not self.trim_silence or len(arr) == 0:
            return arr
        import numpy as np

        magnitude = np.max(np.abs(arr), axis=1)
        active = np.flatnonzero(magnitude > self.silence_threshold)
        if len(active) == 0:
            return arr
        lead_keep = int(rate * self.leading_silence_ms / 1000.0)
        trail_keep = int(rate * self.trailing_silence_ms / 1000.0)
        start = max(0, int(active[0]) - lead_keep)
        end = min(len(arr), int(active[-1]) + 1 + trail_keep)
        return arr[start:end]

    def _ensure_stream(self, rate: int, channels: int) -> None:
        import sounddevice as sd

        if self._stream is not None and self._rate == rate and self._channels == channels:
            return
        self._close_stream()
        self._stream = sd.OutputStream(
            samplerate=rate,
            channels=channels,
            dtype="float32",
            device=self.output_device,
            latency="low",
        )
        self._stream.start()
        self._rate = rate
        self._channels = channels

    @staticmethod
    def _latency_seconds(stream) -> float:
        try:
            latency = getattr(stream, "latency", 0.0) or 0.0
            if isinstance(latency, (tuple, list)):
                latency = latency[-1] if latency else 0.0
            return max(0.0, float(latency))
        except Exception:
            return 0.0

    def _publish_reference(self, block, rate: int, stream) -> None:
        if self.on_reference is None or len(block) == 0:
            return
        try:
            now = time.monotonic()
            start = now + self._latency_seconds(stream)
            with self._lock:
                if self._reference_next_start is not None:
                    start = max(start, float(self._reference_next_start))
                self._reference_next_start = start + (len(block) / float(rate))
            self.on_reference(block.copy(), int(rate), start)
        except Exception:
            # AEC telemetry/reference delivery must never break TTS playback.
            pass

    def play(self, wav: bytes) -> None:
        if not self._continuous_available:
            if self._cancel_event.is_set():
                return
            # The fallback one-shot backend cannot be interrupted safely.  The
            # normal TALUS environment has sounddevice/soundfile installed and
            # therefore uses the cooperative block writer below.
            play_wav_bytes(wav, output_device=self.output_device)
            return

        import numpy as np
        import soundfile as sf

        arr, rate = sf.read(io.BytesIO(wav), dtype="float32", always_2d=True)
        arr = self._trim(arr, int(rate))
        if len(arr) == 0 or self._cancel_event.is_set():
            return
        with self._lock:
            if self._cancel_event.is_set():
                return
            self._ensure_stream(int(rate), int(arr.shape[1]))
            stream = self._stream
            preroll = self._needs_preroll
            if preroll:
                self._needs_preroll = False
        if stream is None:
            return

        if preroll and self.first_preroll_ms > 0 and not self._cancel_event.is_set():
            frames = max(1, int(int(rate) * self.first_preroll_ms / 1000.0))
            # Preroll is silence used only to wake the device; it is intentionally
            # not entered into the AEC reference timeline.
            stream.write(np.zeros((frames, int(arr.shape[1])), dtype="float32"))

        frames_per_write = max(1, int(int(rate) * self.write_block_ms / 1000.0))
        for offset in range(0, len(arr), frames_per_write):
            if self._cancel_event.is_set():
                break
            block_arr = arr[offset : offset + frames_per_write]
            # Publish only audio that is about to be handed to PortAudio.  This
            # prevents a cancelled tail from becoming a phantom echo reference.
            self._publish_reference(block_arr, int(rate), stream)
            stream.write(block_arr)

    def begin_utterance(self) -> None:
        """Arm one silent preroll before the next spoken chunk."""
        with self._lock:
            self._needs_preroll = True

    def reset_cancel(self) -> None:
        with self._lock:
            self._cancel_event.clear()
            self._needs_preroll = True
            self._reference_next_start = None

    def cancel(self) -> None:
        """Request playback cancellation without touching PortAudio cross-thread.

        stream.write() is intentionally performed in short blocks, so the
        playback worker observes this flag quickly and exits safely itself.
        """
        self._cancel_event.set()

    def _close_stream(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
            except Exception:
                pass
            try:
                self._stream.close()
            except Exception:
                pass
        self._stream = None
        self._rate = None
        self._channels = None
        self._needs_preroll = True
        self._reference_next_start = None

    def close(self) -> None:
        # close() is called after the StreamingTtsPlayer playback worker has
        # exited, so PortAudio teardown occurs on a safe control path.
        with self._lock:
            self._close_stream()
