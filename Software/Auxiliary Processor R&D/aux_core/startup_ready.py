"""Fail-closed, one-shot spoken startup handoff for TALUS AUX.

Only a successfully completed, synchronous TTS playback opens conversation
inputs. The selected TtsManager voice is used, not a bundled sound file.
"""
from __future__ import annotations

import threading

from .audio_output import play_wav_bytes


DEFAULT_READY_MESSAGE = "Hello! I'm TALUS. Ready to help wherever I can!"


class StartupNotReady(RuntimeError):
    pass


class StartupReadyGate:
    def __init__(self, state=None, message: str = DEFAULT_READY_MESSAGE):
        self.state = state
        self.message = str(message).strip() or DEFAULT_READY_MESSAGE
        self._lock = threading.RLock()
        self._ready = threading.Event()
        self._phase = "initializing"
        self._publish("initializing")

    @property
    def ready(self) -> bool:
        return self._ready.is_set()

    @property
    def phase(self) -> str:
        return self._phase

    def _publish(self, phase: str, *, error: str | None = None):
        self._phase = phase
        if self.state is not None:
            try:
                payload = {"phase": phase, "ready": self.ready}
                if error is not None:
                    payload["error"] = error
                self.state.update("startup", **payload)
            except Exception:
                # Status instrumentation must not affect input authorization.
                pass

    def require_ready(self):
        if not self.ready:
            raise StartupNotReady("TALUS startup greeting has not finished; conversational input is disabled")

    def announce(self, tts, *, output_device=None, play=None, verify_ready=None) -> bool:
        """Synthesize and synchronously play greeting; return True if newly played.

        `play` is injectable for the live continuous output stream and tests.
        This method must be called *after* model/device readiness is established.
        A failed synthesis/playback never opens the gate or falsely says ready.
        """
        with self._lock:
            if self.ready:
                return False
            self._publish("announcing")
            try:
                # A manually selected voice ID takes precedence. Without an
                # explicit ID, TtsManager can route English to a fallback voice
                # despite the user's active selection. Active multilingual
                # voice-sets still select their own English voice normally.
                registry = getattr(tts, "registry", None)
                options = {"language": "en"}
                if registry is not None and not getattr(registry, "active_set_id", None):
                    selected_id = getattr(registry, "active_id", None)
                    if selected_id:
                        options["voice_id"] = selected_id
                wav, voice = tts.synthesize(self.message, **options)
                if not wav:
                    raise RuntimeError("The startup greeting synthesized empty audio")
                if play is None:
                    play_wav_bytes(wav, output_device=output_device)
                else:
                    play(wav)
                if verify_ready is not None:
                    verify_ready()
            except BaseException as exc:
                self._publish("failed", error=f"{type(exc).__name__}: {exc}")
                raise
            self._ready.set()
            self._publish("ready")
            print("[AUX] Startup greeting finished; conversation is ready.")
            return True
