from pathlib import Path
from types import SimpleNamespace
import wave

import numpy as np

from aux_core.stt import FasterWhisperStt


class _Segment:
    text = " synthetic transcript "


class _FakeModel:
    def __init__(self):
        self.received = None

    def transcribe(self, audio, **kwargs):
        self.received = audio
        return iter([_Segment()]), SimpleNamespace(language="en", language_probability=0.99)


def _write_wav(path: Path, *, rate=24000, seconds=0.1):
    t = np.arange(int(rate * seconds), dtype=np.float32) / rate
    pcm = (0.2 * np.sin(2 * np.pi * 440 * t) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


def test_wav_file_is_decoded_to_numpy_before_faster_whisper(tmp_path):
    wav = tmp_path / "sample.wav"
    _write_wav(wav, rate=24000)
    stt = FasterWhisperStt({"model_path": "."}, tmp_path)
    fake = _FakeModel()
    stt._model = fake

    out = stt.transcribe(wav)

    assert out["text"] == "synthetic transcript"
    assert isinstance(fake.received, np.ndarray)
    assert fake.received.dtype == np.float32
    assert fake.received.ndim == 1
    # 0.1 s at the Whisper-native 16 kHz rate.
    assert abs(fake.received.size - 1600) <= 1


def test_numpy_live_pcm_bypasses_file_decoder(tmp_path):
    stt = FasterWhisperStt({"model_path": "."}, tmp_path)
    fake = _FakeModel()
    stt._model = fake
    pcm = np.zeros(800, dtype=np.float32)

    stt.transcribe(pcm)

    assert isinstance(fake.received, np.ndarray)
    assert fake.received.shape == (800,)
