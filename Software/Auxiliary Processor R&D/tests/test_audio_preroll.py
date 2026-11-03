import sys
import types
import unittest
from unittest.mock import patch

import numpy as np

from aux_core.audio_output import ContinuousWavPlayer


class _FakeStream:
    def __init__(self):
        self.writes = []

    def write(self, arr):
        self.writes.append(np.asarray(arr).copy())


class AudioPrerollTests(unittest.TestCase):
    def test_first_chunk_writes_silence_before_speech(self):
        player = ContinuousWavPlayer(trim_silence=False, first_preroll_ms=100)
        player._continuous_available = True
        stream = _FakeStream()

        def ensure(rate, channels):
            player._stream = stream
            player._rate = rate
            player._channels = channels

        player._ensure_stream = ensure
        fake_soundfile = types.SimpleNamespace(
            read=lambda *args, **kwargs: (np.ones((10, 1), dtype=np.float32), 1000)
        )
        with patch.dict(sys.modules, {"soundfile": fake_soundfile}):
            player.begin_utterance()
            player.play(b"not-a-real-wave")

        self.assertEqual(len(stream.writes), 2)
        self.assertEqual(stream.writes[0].shape, (100, 1))
        self.assertTrue(np.allclose(stream.writes[0], 0.0))
        self.assertTrue(np.allclose(stream.writes[1], 1.0))

    def test_preroll_occurs_once_per_utterance(self):
        player = ContinuousWavPlayer(trim_silence=False, first_preroll_ms=50)
        player._continuous_available = True
        stream = _FakeStream()

        def ensure(rate, channels):
            player._stream = stream
            player._rate = rate
            player._channels = channels

        player._ensure_stream = ensure
        fake_soundfile = types.SimpleNamespace(
            read=lambda *args, **kwargs: (np.ones((5, 1), dtype=np.float32), 1000)
        )
        with patch.dict(sys.modules, {"soundfile": fake_soundfile}):
            player.begin_utterance()
            player.play(b"a")
            player.play(b"b")

        # preroll + speech + speech; there should not be a second preroll
        self.assertEqual(len(stream.writes), 3)
        self.assertTrue(np.allclose(stream.writes[0], 0.0))
        self.assertTrue(np.allclose(stream.writes[1], 1.0))
        self.assertTrue(np.allclose(stream.writes[2], 1.0))


if __name__ == "__main__":
    unittest.main()
