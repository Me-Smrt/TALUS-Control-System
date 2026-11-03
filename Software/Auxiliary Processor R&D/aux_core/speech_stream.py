from __future__ import annotations

import queue
import re
import threading
import time
from dataclasses import dataclass
from typing import Callable


@dataclass
class SpeechChunkerConfig:
    first_min_chars: int = 24
    first_max_chars: int = 140
    min_chars: int = 90
    max_chars: int = 280


class SpeechChunker:
    """Turn an LLM token stream into natural TTS chunks.

    The first chunk is intentionally allowed to be smaller so the robot can
    begin speaking quickly.  Later chunks are larger and may contain more than
    one short sentence, which improves prosody and reduces sentence-by-sentence
    playback seams.
    """

    _BOUNDARY = re.compile(r"[.!?](?:[\"')\]]+)?(?:\s+|$)")
    _SOFT_BOUNDARY = re.compile(r"[;:](?:\s+|$)")

    def __init__(
        self,
        min_chars: int = 90,
        max_chars: int = 280,
        *,
        first_min_chars: int | None = None,
        first_max_chars: int | None = None,
    ) -> None:
        # Backward-compatible defaults: callers that only specify min/max get
        # those same boundaries for the first chunk. The robot's main config
        # passes explicit lower first-chunk values for low-latency speech.
        first_min = min_chars if first_min_chars is None else first_min_chars
        first_max = max_chars if first_max_chars is None else first_max_chars
        self.first_min_chars = max(1, int(first_min))
        self.first_max_chars = max(self.first_min_chars, int(first_max))
        self.min_chars = max(self.first_min_chars, int(min_chars))
        self.max_chars = max(self.min_chars, int(max_chars))
        self.buffer = ""
        self._emitted = False

    def feed(self, text: str) -> list[str]:
        if text:
            self.buffer += str(text)
        out: list[str] = []
        while True:
            threshold = self.first_min_chars if not self._emitted else self.min_chars
            if len(self.buffer) < threshold:
                break
            cap = self.first_max_chars if not self._emitted else self.max_chars
            cut = self._find_cut(threshold, cap)
            if cut is None:
                break
            chunk = self.buffer[:cut].strip()
            self.buffer = self.buffer[cut:].lstrip()
            if chunk:
                out.append(chunk)
                self._emitted = True
        return out


    @staticmethod
    def _protected_at(text: str, cut: int) -> bool:
        """Return True when *cut* falls inside code or LaTeX delimiters.

        The TTS sanitizer can verbalize a complete equation, but not half of one.
        Avoid sending a streamed chunk until the closing math delimiter arrives.
        """
        prefix = text[:cut]
        if prefix.count("```") % 2:
            return True
        # Escaped dollars are not math delimiters.
        dollars = re.sub(r"\\\$", "", prefix)
        display_count = dollars.count("$$")
        if display_count % 2:
            return True
        singles = dollars.replace("$$", "").count("$")
        if singles % 2:
            return True
        if prefix.count(r"\[") > prefix.count(r"\]"):
            return True
        if prefix.count(r"\(") > prefix.count(r"\)"):
            return True
        return False

    def _safe(self, cut: int) -> bool:
        return cut > 0 and not self._protected_at(self.buffer, cut)

    def _find_cut(self, threshold: int, cap: int) -> int | None:
        # Prefer a full sentence boundary once enough text has accumulated.
        # After the first chunk we intentionally wait for a larger amount of
        # text, so several short sentences can share one TTS synthesis call.
        for match in self._BOUNDARY.finditer(self.buffer):
            if match.end() >= threshold and self._safe(match.end()):
                return match.end()

        # Clause boundaries are useful for long list-like sentences.
        if len(self.buffer) >= max(threshold * 2, 120):
            for match in self._SOFT_BOUNDARY.finditer(self.buffer):
                if match.end() >= threshold and self._safe(match.end()):
                    return match.end()

        # For the very first spoken chunk, a comma can be a useful low-latency
        # clause boundary once enough material exists.  Later chunks favor full
        # sentences for smoother prosody.
        if not self._emitted and len(self.buffer) >= min(cap, max(threshold * 2, 60)):
            comma = self.buffer.rfind(",", threshold, cap + 1)
            if comma >= threshold and self._safe(comma + 1):
                return comma + 1

        if len(self.buffer) < cap:
            return None

        # Hard cap: split at the last whitespace before the active cap.
        cut = self.buffer.rfind(" ", threshold, cap + 1)
        candidate = cut + 1 if cut >= threshold else cap
        if self._safe(candidate):
            return candidate
        # Do not split an equation/code block merely to satisfy the cap. Wait
        # until a closing delimiter arrives, then a later feed can emit it.
        return None

    def flush(self) -> list[str]:
        tail = self.buffer.strip()
        self.buffer = ""
        if tail:
            self._emitted = True
            return [tail]
        return []


class StreamingTtsPlayer:
    """Two-stage synth/play pipeline for low-latency continuous speech.

    The old implementation used one worker that synthesized *and then played*
    each sentence.  That guaranteed a dead period between chunks because the
    next sentence could not begin synthesis until the prior sentence finished
    playing.

    This implementation has independent synthesis and playback workers:

        text chunks -> synth queue -> WAV queue -> playback

    While chunk N is playing, chunk N+1 can already be synthesized and buffered.
    Playback order is preserved and only one audio chunk is played at a time.
    """

    def __init__(
        self,
        synthesize: Callable[[str, str | None], bytes],
        play: Callable[[bytes], None],
        *,
        max_queue: int = 8,
        max_audio_queue: int = 3,
        startup_buffer_chunks: int = 1,
        startup_buffer_timeout_ms: float = 1800.0,
        on_error: Callable[[Exception], None] | None = None,
        on_cancel_playback: Callable[[], None] | None = None,
    ) -> None:
        self._synthesize = synthesize
        self._play = play
        self._text_q: queue.Queue[tuple[int, str, str | None] | None] = queue.Queue(
            maxsize=max(1, int(max_queue))
        )
        self._audio_q: queue.Queue[tuple[int, bytes] | None] = queue.Queue(
            maxsize=max(1, int(max_audio_queue))
        )
        self._on_error = on_error
        self._on_cancel_playback = on_cancel_playback
        self._closed = False
        self._cancelled = threading.Event()
        self._seq = 0
        # A tiny startup reservoir avoids the audible "first phrase, long gap,
        # second phrase" artifact when TTS synthesis is only barely faster than
        # playback.  Only the *start* of an utterance is buffered; after playback
        # begins, synthesis and playback continue as the normal two-stage pipe.
        self._startup_buffer_chunks = max(1, int(startup_buffer_chunks))
        self._startup_buffer_timeout_s = max(0.0, float(startup_buffer_timeout_ms) / 1000.0)
        self._input_complete = threading.Event()
        self._startup_changed = threading.Event()
        self._synth_thread = threading.Thread(
            target=self._synth_run,
            name="aux-tts-synth",
            daemon=True,
        )
        self._play_thread = threading.Thread(
            target=self._play_run,
            name="aux-tts-play",
            daemon=True,
        )
        self._synth_thread.start()
        self._play_thread.start()

    def _report(self, exc: Exception) -> None:
        if self._on_error:
            try:
                self._on_error(exc)
            except Exception:
                pass

    def _synth_run(self) -> None:
        while True:
            item = self._text_q.get()
            try:
                if item is None:
                    self._audio_q.put(None)
                    return
                seq, text, language = item
                if self._cancelled.is_set():
                    continue
                try:
                    wav = self._synthesize(text, language)
                except Exception as exc:
                    self._report(exc)
                    continue
                if self._cancelled.is_set():
                    continue
                self._audio_q.put((seq, wav))
                self._startup_changed.set()
            finally:
                self._text_q.task_done()

    def _wait_for_startup_buffer(self) -> None:
        """Wait briefly for a small reservoir of synthesized chunks.

        The first WAV has already been removed from ``_audio_q`` by the playback
        worker, so ``1 + qsize()`` is the number of ready chunks.  Once the LLM
        side marks submissions complete, a short reply is allowed to start with
        fewer than the configured target instead of waiting for a nonexistent
        second chunk.  A timeout is the final safety valve for slow synthesis.
        """
        if self._startup_buffer_chunks <= 1 or self._cancelled.is_set():
            return
        deadline = time.monotonic() + self._startup_buffer_timeout_s
        while not self._cancelled.is_set():
            ready = 1 + self._audio_q.qsize()
            submitted = max(1, int(self._seq))
            target = self._startup_buffer_chunks
            if self._input_complete.is_set():
                target = min(target, submitted)
            if ready >= target:
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            self._startup_changed.wait(min(0.05, remaining))
            self._startup_changed.clear()

    def _play_run(self) -> None:
        first_play = True
        while True:
            item = self._audio_q.get()
            try:
                if item is None:
                    return
                _seq, wav = item
                if self._cancelled.is_set():
                    continue
                if first_play:
                    self._wait_for_startup_buffer()
                    first_play = False
                    if self._cancelled.is_set():
                        continue
                try:
                    self._play(wav)
                except Exception as exc:
                    self._report(exc)
            finally:
                self._audio_q.task_done()

    def submit(self, text: str, language: str | None = None) -> None:
        if self._closed or self._cancelled.is_set() or not str(text).strip():
            return
        self._seq += 1
        self._text_q.put((self._seq, str(text).strip(), language))

    def finish_submissions(self) -> None:
        """Tell the startup buffer that no additional text chunks are coming."""
        self._input_complete.set()
        self._startup_changed.set()

    def wait(self) -> None:
        """Wait until both synthesis and playback have drained."""
        self.finish_submissions()
        self._text_q.join()
        self._audio_q.join()

    @staticmethod
    def _drain(q: queue.Queue) -> None:
        while True:
            try:
                q.get_nowait()
                q.task_done()
            except queue.Empty:
                break

    def cancel(self) -> None:
        """Drop pending speech and request immediate playback cancellation."""
        if self._cancelled.is_set():
            return
        self._cancelled.set()
        self._input_complete.set()
        self._startup_changed.set()
        self._drain(self._text_q)
        self._drain(self._audio_q)
        if self._on_cancel_playback:
            try:
                self._on_cancel_playback()
            except Exception:
                pass

    def close(self, *, wait: bool = True) -> None:
        if self._closed:
            return
        if wait and not self._cancelled.is_set():
            self.wait()
        self._closed = True
        self._text_q.put(None)
        self._synth_thread.join(timeout=5)
        # The synth worker forwards the playback sentinel after all prior WAVs.
        self._play_thread.join(timeout=5)
