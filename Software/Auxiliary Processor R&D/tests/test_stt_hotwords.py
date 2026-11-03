from pathlib import Path
import numpy as np

from aux_core.stt import FasterWhisperStt


class _Info:
    language = "en"
    language_probability = 0.9


class _Model:
    def __init__(self):
        self.kwargs = None

    def transcribe(self, audio, **kwargs):
        self.kwargs = kwargs
        return iter([]), _Info()


def test_config_hotwords_are_passed_to_whisper():
    stt = FasterWhisperStt({"model_path": ".", "hotwords": ["TALUS", "Talos"]}, Path("."))
    stt._model = _Model()
    stt.transcribe(np.zeros(1600, dtype=np.float32))
    assert stt._model.kwargs["hotwords"] == "TALUS Talos"


def test_hotwords_can_be_disabled_for_training_samples():
    stt = FasterWhisperStt({"model_path": ".", "hotwords": ["TALUS", "Talos"]}, Path("."))
    stt._model = _Model()
    stt.transcribe(np.zeros(1600, dtype=np.float32), use_config_hotwords=False)
    assert stt._model.kwargs["hotwords"] is None
