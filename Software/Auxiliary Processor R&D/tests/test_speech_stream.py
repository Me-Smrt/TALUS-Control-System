import threading
import time
import unittest

from aux_core.speech_stream import SpeechChunker, StreamingTtsPlayer


class SpeechChunkerV033Tests(unittest.TestCase):
    def test_first_chunk_can_be_smaller_than_later_chunks(self):
        c = SpeechChunker(first_min_chars=20, min_chars=80, max_chars=200)
        out = c.feed("Hello there! I'm ready to help with that. ")
        self.assertEqual(len(out), 1)
        self.assertIn("ready to help", out[0])
        # A later short sentence should remain buffered because subsequent
        # chunks target more context for smoother prosody.
        self.assertEqual(c.feed("This is short. "), [])


class StreamingTtsPipelineTests(unittest.TestCase):
    def test_synthesis_runs_ahead_of_playback(self):
        events = []
        lock = threading.Lock()

        def mark(name, item):
            with lock:
                events.append((name, item, time.monotonic()))

        def synth(text, language):
            mark("synth_start", text)
            time.sleep(0.03)
            mark("synth_end", text)
            return text.encode()

        def play(wav):
            text = wav.decode()
            mark("play_start", text)
            time.sleep(0.16)
            mark("play_end", text)

        p = StreamingTtsPlayer(synth, play, max_queue=4, max_audio_queue=2)
        p.submit("one")
        p.submit("two")
        p.wait()
        p.close()

        times = {(name, item): ts for name, item, ts in events}
        self.assertLess(times[("synth_start", "two")], times[("play_end", "one")])
        self.assertLess(times[("play_start", "one")], times[("play_start", "two")])

    def test_playback_can_start_before_generation_is_finished(self):
        playback_started = threading.Event()

        def synth(text, language):
            time.sleep(0.01)
            return text.encode()

        def play(wav):
            playback_started.set()
            time.sleep(0.05)

        p = StreamingTtsPlayer(synth, play)
        p.submit("first chunk")
        self.assertTrue(playback_started.wait(0.5))
        # At this point a caller may still be receiving/generating later LLM
        # tokens; no wait()/close() was required to begin playback.
        p.submit("second chunk")
        p.wait()
        p.close()


if __name__ == "__main__":
    unittest.main()
