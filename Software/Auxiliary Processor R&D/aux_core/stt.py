from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np


class FasterWhisperStt:
    """Local Faster-Whisper wrapper with a decoder-independent PCM path.

    Live microphone audio and ordinary audio files are normalized to mono
    float32/16 kHz NumPy PCM before being handed to Faster-Whisper. Passing an
    ndarray makes Faster-Whisper skip its PyAV decoder entirely, which keeps the
    TALUS STT path portable across Windows/Linux and insulated from PyAV API
    changes. If SoundFile cannot decode a supplied non-WAV/container format, we
    fall back to Faster-Whisper's native decoder for that uncommon case.
    """

    TARGET_SAMPLE_RATE = 16000

    def __init__(self, cfg: dict[str, Any], root: Path):
        self.cfg = dict(cfg)
        p = Path(str(cfg.get("model_path", "")))
        self.path = p if p.is_absolute() else (root / p).resolve()
        self._model = None

    def available(self) -> bool:
        return self.path.is_dir()

    def _load(self):
        if self._model is not None:
            return
        if not self.available():
            raise RuntimeError(f"STT model directory not found: {self.path}")
        from faster_whisper import WhisperModel

        self._model = WhisperModel(
            str(self.path),
            device=str(self.cfg.get("device", "auto")),
            compute_type=str(self.cfg.get("compute_type", "default")),
            local_files_only=True,
        )

    @staticmethod
    def _mono_float32(audio: np.ndarray) -> np.ndarray:
        arr = np.asarray(audio, dtype=np.float32)
        if arr.ndim == 0:
            arr = arr.reshape(1)
        elif arr.ndim > 1:
            # SoundFile uses samples x channels. Live capture is expected to do
            # the same; averaging gives a deterministic mono mixdown.
            arr = np.mean(arr, axis=-1, dtype=np.float32)
        return np.ascontiguousarray(arr.reshape(-1), dtype=np.float32)

    @classmethod
    def _resample_pcm(cls, audio: np.ndarray, source_rate: int) -> np.ndarray:
        arr = cls._mono_float32(audio)
        source_rate = int(source_rate)
        if source_rate <= 0:
            raise ValueError(f"Invalid audio sample rate: {source_rate}")
        if source_rate == cls.TARGET_SAMPLE_RATE or arr.size == 0:
            return arr

        # A small NumPy-only linear resampler is sufficient for speech/STT and
        # avoids adding a heavyweight platform-specific DSP dependency. Final
        # live microphone capture will normally already provide 16 kHz PCM.
        target_len = max(1, int(round(arr.size * cls.TARGET_SAMPLE_RATE / source_rate)))
        src_x = np.arange(arr.size, dtype=np.float64)
        dst_x = np.linspace(0.0, max(arr.size - 1, 0), target_len, dtype=np.float64)
        out = np.interp(dst_x, src_x, arr).astype(np.float32, copy=False)
        return np.ascontiguousarray(out)

    @classmethod
    def _decode_local_audio(cls, audio: Any):
        if isinstance(audio, np.ndarray):
            return cls._mono_float32(audio)

        if isinstance(audio, (str, Path)):
            path = Path(audio)
            if path.is_file():
                try:
                    import soundfile as sf

                    pcm, sample_rate = sf.read(
                        str(path), dtype="float32", always_2d=False
                    )
                    return cls._resample_pcm(pcm, int(sample_rate))
                except Exception:
                    # Preserve support for formats SoundFile/libsndfile cannot
                    # decode. Faster-Whisper may decode those through PyAV.
                    return str(path)

        return audio

    @staticmethod
    def _hotword_text(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            text = value.strip()
            return text or None
        if isinstance(value, (list, tuple, set)):
            text = " ".join(str(v).strip() for v in value if str(v).strip())
            return text or None
        text = str(value).strip()
        return text or None

    def transcribe(
        self,
        audio,
        *,
        language: str | None = None,
        hotwords: str | list[str] | None = None,
        use_config_hotwords: bool = True,
    ) -> dict[str, Any]:
        self._load()
        prepared = self._decode_local_audio(audio)
        if hotwords is None and use_config_hotwords:
            hotwords = self.cfg.get("hotwords")
        hotword_text = self._hotword_text(hotwords)
        try:
            segments, info = self._model.transcribe(
                prepared,
                beam_size=int(self.cfg.get("beam_size", 1)),
                language=language or self.cfg.get("language"),
                condition_on_previous_text=bool(
                    self.cfg.get("condition_on_previous_text", False)
                ),
                vad_filter=False,
                hotwords=hotword_text,
            )
        except TypeError as exc:
            # PyAV 19 removed metadata_errors from av.open. This only applies to
            # the uncommon fallback path above; normal WAV/live PCM is ndarray
            # based and never reaches PyAV.
            if "metadata_errors" in str(exc):
                raise RuntimeError(
                    "The installed faster-whisper/PyAV versions are incompatible "
                    "for this compressed audio format. WAV/live PCM uses TALUS's "
                    "portable NumPy path and is unaffected."
                ) from exc
            raise

        # Materialize once so we can expose quality metrics to the live speech
        # gate.  These are useful for rejecting fan/desk/background noises that
        # VAD occasionally classifies as speech before they reach engagement.
        segment_list = list(segments)
        text = " ".join(s.text.strip() for s in segment_list if s.text.strip()).strip()

        weighted_logprob = 0.0
        weighted_no_speech = 0.0
        total_weight = 0.0
        compression_ratio = 0.0
        speech_duration_s = 0.0
        for seg in segment_list:
            try:
                duration = max(0.01, float(seg.end) - float(seg.start))
            except Exception:
                duration = 1.0
            speech_duration_s += duration
            total_weight += duration
            try:
                weighted_logprob += float(seg.avg_logprob) * duration
            except Exception:
                pass
            try:
                weighted_no_speech += float(seg.no_speech_prob) * duration
            except Exception:
                pass
            try:
                compression_ratio = max(compression_ratio, float(seg.compression_ratio))
            except Exception:
                pass

        avg_logprob = weighted_logprob / total_weight if total_weight else None
        no_speech_probability = weighted_no_speech / total_weight if total_weight else None

        return {
            "text": text,
            "language": getattr(info, "language", language),
            "language_probability": float(
                getattr(info, "language_probability", 0.0) or 0.0
            ),
            "segment_count": len(segment_list),
            "avg_logprob": avg_logprob,
            "no_speech_probability": no_speech_probability,
            "compression_ratio": compression_ratio if segment_list else None,
            "speech_duration_s": speech_duration_s,
        }
