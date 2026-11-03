from __future__ import annotations

import queue
import math
import re
import threading
import time
from collections import deque

from .audio_output import ContinuousWavPlayer
from .aec import AdaptiveEchoCanceller, EchoReferenceTimeline
from .speech_stream import SpeechChunker, StreamingTtsPlayer


class BargeInInterrupt(RuntimeError):
    """Internal control-flow signal raised when near-end speech interrupts TTS."""


class AudioConversationLoop:
    """Optional real microphone loop.

    Live microphone processing runs continuously, including while TTS is playing.
    When AEC is enabled, the exact speaker PCM is used as a far-end reference so
    residual near-end speech can trigger a conservative full-duplex barge-in.
    Without AEC, the legacy safe policy still ignores input during TTS.
    """

    def __init__(self, cfg, stt, engagement, conversation, tts, pi, state, telemetry=None, *, debug=False):
        self.cfg = cfg
        self.stt = stt
        self.engagement = engagement
        self.conversation = conversation
        self.tts = tts
        self.pi = pi
        self.state = state
        self.telemetry = telemetry
        self.debug = bool(debug)
        self.speaking = False
        self.active_language = str(self.cfg.get("default_conversation_language", "en") or "en").split("-", 1)[0].lower()



    @staticmethod
    def _script_language(text: str) -> str | None:
        value = str(text or "")
        # Strong-script evidence is more trustworthy than Whisper's language
        # probability on short utterances. Han+Kana is Japanese; bare Han is
        # treated as Mandarin for the currently-supported East Asian routes.
        if re.search(r"[\u3040-\u30ff]", value):
            return "ja"
        if re.search(r"[\uac00-\ud7af]", value):
            return "ko"
        if re.search(r"[\u0600-\u06ff]", value):
            return "ar"
        if re.search(r"[\u0900-\u097f]", value):
            return "hi"
        if re.search(r"[\u0400-\u04ff]", value):
            return "uk" if re.search(r"[іїєґІЇЄҐ]", value) else "ru"
        if re.search(r"[\u4e00-\u9fff]", value):
            return "zh"
        return None

    def _select_turn_language(self, result, text, wake=None):
        current = self.active_language or "en"
        scripted = self._script_language(text)
        if scripted:
            self.active_language = scripted
            return scripted, "strong_script"

        candidate = str((result or {}).get("language") or current).split("-", 1)[0].lower()
        try:
            confidence = float((result or {}).get("language_probability", 0.0) or 0.0)
        except Exception:
            confidence = 0.0

        tokens = self.engagement._tokens(text) if hasattr(self.engagement, "_tokens") else str(text or "").split()
        wake_only = bool(wake) and len(tokens) <= int(self.cfg.get("wake_only_max_tokens", 2))
        if wake_only:
            # The word TALUS is not enough linguistic evidence to switch the
            # whole conversation language. Preserve the last accepted language.
            return current, "wake_only_inherit"

        threshold = float(self.cfg.get("language_switch_min_confidence", 0.70))
        if candidate != current and confidence < threshold:
            return current, "low_confidence_inherit"

        if candidate:
            self.active_language = candidate
            return candidate, "stt_confident" if candidate != current else "stt_same"
        return current, "fallback"

    def _is_wake_only_text(self, text: str, wake=None) -> bool:
        """Return True when an utterance contains only TALUS wake/address tokens.

        This is intentionally broader than the language-switch wake-only check:
        repeated aliases such as "TALUS Talus Telus" are still semantically
        just an attention call and must never become an LLM content turn.
        """
        if not wake:
            return False
        tokens = self.engagement._tokens(text) if hasattr(self.engagement, "_tokens") else str(text or "").casefold().split()
        if not tokens:
            return False
        cfg = getattr(self.engagement, "cfg", {}) or {}
        allowed = {
            str(cfg.get("wake_name", "TALUS") or "TALUS").strip().casefold(),
        }
        allowed.update(
            str(v).strip().casefold() for v in cfg.get("wake_name_aliases", []) if str(v).strip()
        )
        allowed.update(
            str(v).strip().casefold() for v in cfg.get("wake_name_prefixes", []) if str(v).strip()
        )
        for phrase in cfg.get("wake_phrases", []):
            if hasattr(self.engagement, "_tokens"):
                allowed.update(self.engagement._tokens(str(phrase or "")))
            else:
                allowed.update(str(phrase or "").casefold().split())
        return bool(tokens) and all(token in allowed for token in tokens)

    def _speech_gate(self, audio, result, sr: int):
        gate = self.cfg.get("speech_gate", {}) or {}
        if not bool(gate.get("enabled", True)):
            return True, "disabled", {}

        try:
            import numpy as np
            arr = np.asarray(audio, dtype=np.float32).reshape(-1)
            duration_s = float(arr.size) / float(sr) if sr else 0.0
            rms = float(np.sqrt(np.mean(np.square(arr), dtype=np.float64))) if arr.size else 0.0
        except Exception:
            duration_s, rms = 0.0, 0.0

        metrics = {
            "duration_s": duration_s,
            "rms": rms,
            "avg_logprob": (result or {}).get("avg_logprob"),
            "no_speech_probability": (result or {}).get("no_speech_probability"),
            "language_probability": float((result or {}).get("language_probability", 0.0) or 0.0),
        }

        if duration_s * 1000.0 < float(gate.get("min_duration_ms", self.cfg.get("min_speech_ms", 250))):
            return False, "too_short", metrics
        if rms < float(gate.get("min_rms", 0.0025)):
            return False, "low_energy", metrics

        no_speech = metrics["no_speech_probability"]
        if no_speech is not None and float(no_speech) > float(gate.get("max_no_speech_probability", 0.58)):
            return False, "whisper_no_speech", metrics
        avg_logprob = metrics["avg_logprob"]
        if avg_logprob is not None and float(avg_logprob) < float(gate.get("min_avg_logprob", -1.25)):
            return False, "low_transcription_likelihood", metrics

        text = str((result or {}).get("text", "") or "").strip()
        wake = self.engagement.wake_match(text) if text else None
        tokens = self.engagement._tokens(text) if hasattr(self.engagement, "_tokens") else text.split()
        wake_only = bool(wake) and len(tokens) <= int(self.cfg.get("wake_only_max_tokens", 2))
        if wake_only and metrics["language_probability"] < float(gate.get("wake_only_min_language_confidence", 0.35)):
            return False, "suspicious_low_confidence_wake", metrics

        return True, "speech_like", metrics

    def _barge_post_stt_gate(self, audio, result, sr: int, capture_meta: dict):
        """Stricter final validation for an already-confirmed interruption.

        The ordinary speech gate is intentionally permissive enough for quiet
        conversational turns.  A barge-in is riskier because a false positive
        stops TALUS mid-sentence, so it gets a second, stricter check using both
        Whisper quality and the AEC trigger metrics.
        """
        accepted, reason, metrics = self._speech_gate(audio, result, sr)
        if not accepted:
            return accepted, reason, metrics
        aec_cfg = dict(self.cfg.get("aec", {}) or {})
        cfg = dict((aec_cfg.get("barge_in", {}) or {}).get("post_stt_gate", {}) or {})
        trigger = dict((capture_meta or {}).get("aec", {}) or {})
        rms = float(metrics.get("rms", 0.0) or 0.0)
        if rms < float(cfg.get("min_rms", 0.0045)):
            return False, "barge_low_energy", metrics
        no_speech = metrics.get("no_speech_probability")
        if no_speech is not None and float(no_speech) > float(cfg.get("max_no_speech_probability", 0.45)):
            return False, "barge_whisper_no_speech", metrics
        avg_logprob = metrics.get("avg_logprob")
        if avg_logprob is not None and float(avg_logprob) < float(cfg.get("min_avg_logprob", -0.90)):
            return False, "barge_low_transcription_likelihood", metrics
        trigger_mic = float(trigger.get("mic_rms", 0.0) or 0.0)
        if trigger_mic < float(cfg.get("min_trigger_mic_rms", 0.0025)):
            return False, "barge_trigger_mic_too_quiet", metrics
        trigger_ratio = float(trigger.get("residual_to_mic_ratio", 0.0) or 0.0)
        if trigger_ratio > float(cfg.get("max_trigger_residual_to_mic_ratio", 1.60)):
            return False, "barge_trigger_residual_unstable", metrics
        return True, "barge_speech_like", metrics

    def _debug_speech_gate(self, accepted, reason, metrics):
        if not self.debug:
            return
        status = "accepted" if accepted else "ignored"
        parts = [f"[AUX] speech_gate={status}", f"reason={reason}"]
        try:
            parts.append(f"rms={float(metrics.get('rms', 0.0)):.4f}")
            parts.append(f"duration={float(metrics.get('duration_s', 0.0)):.2f}s")
        except Exception:
            pass
        if metrics.get("no_speech_probability") is not None:
            parts.append(f"no_speech={float(metrics['no_speech_probability']):.0%}")
        if metrics.get("avg_logprob") is not None:
            parts.append(f"avg_logprob={float(metrics['avg_logprob']):.2f}")
        print(" ".join(parts))

    def _debug_stt(self, result):
        if not self.debug:
            return
        text = str((result or {}).get("text", "") or "").strip()
        if not text:
            return
        language = (result or {}).get("language") or "und"
        try:
            probability = float((result or {}).get("language_probability", 0.0) or 0.0)
        except Exception:
            probability = 0.0
        print(f"you> {text}")
        print(f"[AUX] STT language={language} confidence={probability:.0%}")

    def _debug_engagement(self, decision):
        if not self.debug:
            return
        decision = decision or {}
        status = "accepted" if decision.get("accept") else "ignored"
        try:
            score = float(decision.get("score", 0.0) or 0.0)
        except Exception:
            score = 0.0
        reason = decision.get("reason") or "unknown"
        wake = decision.get("wake") if isinstance(decision, dict) else None
        suffix = ""
        if isinstance(wake, dict):
            raw = wake.get("raw_alias") or wake.get("canonical")
            canonical = wake.get("canonical")
            kind = wake.get("kind")
            bits = [str(x) for x in (raw, canonical, kind) if x]
            if bits:
                suffix = " wake=" + " -> ".join(bits[:2])
                if kind:
                    suffix += f" ({kind})"
        print(f"[AUX] engagement={status} score={score:.2f} reason={reason}{suffix}")

    def _refresh_engagement_after_reply(self):
        """Start the follow-up window after TALUS finishes speaking."""
        try:
            deadline = self.engagement.touch()
            if self.debug:
                window = float(self.engagement.cfg.get("active_window_s", 25))
                print(f"[AUX] engagement=active_window refreshed={window:.0f}s after_reply")
            return deadline
        except Exception:
            return None

    def _debug_turn_diagnostics(self, out):
        if not self.debug or not isinstance(out, dict):
            return
        if out.get("reasoning_mode"):
            try:
                score = float(out.get("reasoning_score", 0.0) or 0.0)
            except Exception:
                score = 0.0
            print(
                f"[AUX] reasoning={out.get('reasoning_mode')} "
                f"({out.get('reasoning_reason', 'unknown')}; score={score:.2f})"
            )
        if out.get("verification_used"):
            print("[AUX] verification=quantitative_second_pass")
        if out.get("knowledge_sources"):
            names = ", ".join(
                str(x.get("source_id"))
                for x in out.get("knowledge_sources", [])[:5]
                if isinstance(x, dict) and x.get("source_id")
            )
            if names:
                print(f"[AUX] local knowledge: {names}")
        if out.get("actions"):
            suffix = f" ({out.get('visual_reason')})" if out.get("visual_reason") else ""
            auto = "automatic " if out.get("automatic_vision") else ""
            print(f"[AUX] {auto}actions={','.join(out['actions'])}{suffix}")
        if out.get("temporal_observation"):
            print(
                f"[AUX] temporal observation={out.get('temporal_samples', 0)} frame(s) "
                f"over {out.get('temporal_duration_ms') or 0} ms"
            )
        if out.get("behavior_intent"):
            br = out.get("behavior_result") or {}
            print(
                f"[AUX] behavior={out['behavior_intent']} "
                f"status={br.get('status', 'unknown')} executed={bool(br.get('executed', False))}"
            )
        if out.get("onboarding") and out["onboarding"].get("action"):
            print(f"[AUX] identity={out['onboarding']['action']}")
        if out.get("camera_id"):
            print(f"[AUX] camera={out['camera_id']}")

    @staticmethod
    def _barge_metrics_ok(metrics: dict, cfg: dict) -> tuple[bool, str]:
        """Conservative double-talk gate on the AEC residual.

        v0.6.2 separates *reference coverage* from *reference energy*.  A quiet
        syllable gap is not the same as a missing far-end timeline, and it must
        not reset an otherwise valid interruption.  A strong near-end override
        also allows a clearly independent human voice to interrupt before the
        lightweight spectral canceller has demonstrated strong ERLE, provided
        the reference/alignment has at least warmed up globally.
        """
        metrics = metrics or {}
        coverage = float(metrics.get("reference_coverage", 0.0) or 0.0)
        if not bool(metrics.get("reference_present", False)) and coverage <= 0.0:
            return False, "no_reference"
        if coverage < float(cfg.get("min_reference_coverage", 0.70)):
            return False, "reference_gap"

        residual = float(metrics.get("residual_rms", 0.0) or 0.0)
        mic = float(metrics.get("mic_rms", 0.0) or 0.0)
        ref = float(metrics.get("reference_rms", 0.0) or 0.0)
        ratio = float(metrics.get("residual_to_mic_ratio", 0.0) or 0.0)
        corr = abs(float(metrics.get("reference_correlation", 0.0) or 0.0))
        erle = float(metrics.get("erle_db", 0.0) or 0.0)
        ready = bool(metrics.get("aec_ready", False))
        reference_active = bool(metrics.get("reference_active", metrics.get("reference_present", False)))
        good_age = metrics.get("good_echo_age_ms")

        if residual < float(cfg.get("min_residual_rms", 0.0040)):
            return False, "residual_too_quiet"
        # The residual is derived from the microphone and should not become
        # dramatically louder than the raw microphone signal.  When that happens
        # the adaptive subtraction is numerically unstable, not evidence of a
        # suddenly-loud near-end talker.  The v0.6.2 fan false-positive was
        # residual=0.0054 with mic=0.0002 (ratio 22.66).
        if mic < float(cfg.get("min_barge_mic_rms", 0.0025)):
            return False, "mic_too_quiet"
        if ratio > float(cfg.get("max_residual_to_mic_ratio", 1.60)):
            return False, "residual_unstable"
        if reference_active and ref > 1e-8:
            mic_ref_ratio = mic / ref
            if mic_ref_ratio < float(cfg.get("min_mic_to_reference_ratio", 0.02)):
                return False, "far_end_overwhelms_mic"

        # Natural pauses inside TALUS speech have timeline coverage but almost
        # no far-end energy.  In that moment there is little echo to cancel, so
        # a speech-like, energetic residual may count as near-end evidence once
        # the current acoustic path has been verified recently.
        if not reference_active:
            max_age = float(cfg.get("max_good_echo_age_ms", 900.0))
            quiet_min = float(cfg.get("far_end_quiet_min_mic_rms", 0.0060))
            if ready and good_age is not None and float(good_age) <= max_age and mic >= quiet_min:
                return True, "near_end_during_far_end_pause"
            return False, "far_end_quiet"

        if ratio < float(cfg.get("min_residual_to_mic_ratio", 0.22)):
            return False, "echo_dominant"

        if not ready:
            # Real double-talk can reduce simple reference correlation before the
            # spectral AEC shows a pretty ERLE number.  Permit an override only
            # when the microphone is substantially stronger than the speaker
            # reference and the residual looks overwhelmingly near-end.  This
            # path still requires Silero VAD plus sustained evidence in run().
            adapted = int(metrics.get("adapted_blocks", 0) or 0)
            override = bool(
                adapted >= int(cfg.get("override_min_adapted_blocks", 4))
                and corr <= float(cfg.get("unarmed_near_end_max_corr", 0.15))
                and ratio >= float(cfg.get("unarmed_near_end_min_residual_ratio", 0.72))
                and mic >= float(cfg.get("unarmed_near_end_min_mic_rms", 0.010))
                and ref >= float(cfg.get("unarmed_near_end_min_reference_rms", 0.0015))
                and mic >= ref * float(cfg.get("unarmed_near_end_min_mic_ref_ratio", 2.0))
            )
            if override:
                return True, "strong_near_end_override"
            return False, "aec_not_ready"

        max_age = float(cfg.get("max_good_echo_age_ms", 900.0))
        if good_age is None or float(good_age) > max_age:
            return False, "echo_path_stale"

        # If the residual still strongly resembles far-end speech, require
        # local evidence that the canceller is reducing the echo.  Low
        # correlation is expected when a separate near-end human dominates.
        low_corr_override = float(cfg.get("near_end_low_correlation_override", 0.35))
        if corr > low_corr_override and erle < float(cfg.get("min_erle_db", 1.0)):
            return False, "aec_not_converged"
        max_echo_corr = float(cfg.get("max_echo_only_correlation", 0.94))
        if corr >= max_echo_corr and ratio < float(cfg.get("high_corr_min_residual_ratio", 0.50)):
            return False, "far_end_still_dominant"
        return True, "double_talk_likely"

    def run(self):
        if not self.cfg.get("enabled", False):
            raise RuntimeError("audio_loop_disabled_in_config")

        import numpy as np
        import sounddevice as sd
        from silero_vad import VADIterator, load_silero_vad

        sr = int(self.cfg.get("sample_rate", 16000))
        block = int(self.cfg.get("block_samples", 512))
        mic_q: queue.Queue = queue.Queue(maxsize=max(32, int(sr / max(1, block)) * 4))
        # Capture may physically open during startup, but NO audio is queued
        # for VAD/STT while the startup greeting is playing.
        capture_allowed = threading.Event()
        capture_ready = threading.Event()
        utterance_q: queue.Queue = queue.Queue()
        stop_capture = threading.Event()
        barge_event = threading.Event()
        active_player_lock = threading.RLock()
        active_player = [None]
        speaker_epoch = [None]

        aec_cfg = dict(self.cfg.get("aec", {}) or {})
        aec_enabled = bool(aec_cfg.get("enabled", False))
        reference = EchoReferenceTimeline(sr, retain_s=float(aec_cfg.get("reference_retain_s", 8.0)))
        aec = AdaptiveEchoCanceller(aec_cfg, reference, sr) if aec_enabled else None
        barge_cfg = dict(aec_cfg.get("barge_in", {}) or {})
        barge_enabled = bool(aec_enabled and barge_cfg.get("enabled", True))

        if self.debug:
            print("[AUX] Live STT console: microphone/VAD/STT input; keyboard input is disabled.")
            print("[AUX] Transcriptions appear as you>. Rejected utterances remain visible with the engagement reason.")
            print("[AUX] Ctrl+C exits.")
            try:
                selected = self.cfg.get("input_device")
                if selected is None:
                    selected = sd.default.device[0]
                info = sd.query_devices(selected, "input")
                print(f"[AUX] microphone={info.get('name', selected)} device={selected}")
            except Exception:
                pass
            if aec_enabled:
                print(
                    f"[AUX] AEC=adaptive_spectral barge_in={'enabled' if barge_enabled else 'disabled'} "
                    f"initial_delay={float(aec_cfg.get('reference_delay_ms', 45.0)):.0f}ms"
                )
            else:
                print("[AUX] AEC=disabled; microphone remains suppressed during TTS.")

        stream_cfg = self.tts.cfg.get("streaming", {})
        sink = ContinuousWavPlayer(
            output_device=self.cfg.get("output_device"),
            trim_silence=bool(stream_cfg.get("trim_chunk_silence", True)),
            leading_silence_ms=float(stream_cfg.get("leading_silence_ms", 20)),
            trailing_silence_ms=float(stream_cfg.get("trailing_silence_ms", 70)),
            first_preroll_ms=float(stream_cfg.get("first_preroll_ms", 180)),
            write_block_ms=float(aec_cfg.get("playback_write_block_ms", 20.0)),
            on_reference=reference.push if aec_enabled else None,
        )

        def cb(indata, frames, time_info, status):
            if not capture_allowed.is_set():
                return
            chunk = indata[:, 0].copy()
            # monotonic() is used for both the microphone and speaker-reference
            # timelines.  Infer block start from callback arrival time.
            start = time.monotonic() - (len(chunk) / float(sr))
            try:
                mic_q.put_nowait((chunk, start))
            except queue.Full:
                # Prefer the newest live audio to an ever-growing latency tail.
                try:
                    mic_q.get_nowait()
                except queue.Empty:
                    pass
                try:
                    mic_q.put_nowait((chunk, start))
                except queue.Full:
                    pass

        def synthesize_wav(text, language=None):
            wav, _voice = self.tts.synthesize(text, language=language)
            return wav

        def request_barge(metrics):
            if not barge_enabled or barge_event.is_set():
                return
            # This event is the single atomic handoff between the capture thread
            # and the conversation/TTS thread.  ContinuousWavPlayer.cancel() is
            # cooperative, so no PortAudio stream is aborted/closed cross-thread.
            barge_event.set()
            if self.debug:
                age = metrics.get("good_echo_age_ms")
                age_text = "n/a" if age is None else f"{float(age):.0f}ms"
                print(
                    "[AUX] barge_in=confirmed "
                    f"residual={float(metrics.get('residual_rms', 0.0)):.4f} "
                    f"mic={float(metrics.get('mic_rms', 0.0)):.4f} "
                    f"ref={float(metrics.get('reference_rms', 0.0)):.4f} "
                    f"coverage={float(metrics.get('reference_coverage', 0.0)):.0%} "
                    f"ratio={float(metrics.get('residual_to_mic_ratio', 0.0)):.2f} "
                    f"corr={float(metrics.get('reference_correlation', 0.0)):.2f} "
                    f"erle={float(metrics.get('erle_db', 0.0)):.1f}dB "
                    f"ready={bool(metrics.get('aec_ready', False))} "
                    f"echo_age={age_text} "
                    f"delay={float(metrics.get('delay_ms', 0.0)):.0f}ms"
                )
            with active_player_lock:
                player = active_player[0]
                if player is not None:
                    try:
                        player.cancel()
                    except Exception as exc:
                        print(f"[AUX TTS ERROR] barge-in cancel failed: {type(exc).__name__}: {exc}")
                else:
                    sink.cancel()
            # Keep the already-played reference timeline until the near-end
            # utterance has completed.  Clearing it here made the remainder of
            # a real interruption look like unreferenced microphone audio.

        def play_wav(wav):
            self.speaking = True
            if speaker_epoch[0] is None:
                speaker_epoch[0] = time.monotonic()
            try:
                sink.play(wav)
            finally:
                self.speaking = False

        def capture_worker():
            try:
                model = load_silero_vad(onnx=True)
                vad = VADIterator(
                    model,
                    threshold=float(self.cfg.get("vad_threshold", 0.55)),
                    sampling_rate=sr,
                    min_silence_duration_ms=int(self.cfg.get("end_silence_ms", 500)),
                )
            except BaseException as exc:
                utterance_q.put((None, {"error": exc}))
                return
            block_ms = (block / float(sr)) * 1000.0
            pre_roll_ms = float(barge_cfg.get("pre_roll_ms", 450.0))
            pre_roll = deque(maxlen=max(1, int(math.ceil(pre_roll_ms / max(1.0, block_ms)))))
            speech = []
            active = False
            current_barge = False
            speech_started = None
            barge_triggered = False
            barge_evidence_ms = 0.0
            barge_last_reason = None
            barge_last_good_monotonic = None
            barge_last_log_monotonic = 0.0
            last_aec_metrics = {}
            skipped_tts = False

            def reset_vad_state():
                nonlocal active, speech, current_barge, speech_started, barge_triggered, barge_evidence_ms, barge_last_reason, barge_last_good_monotonic
                active = False
                speech = []
                current_barge = False
                speech_started = None
                barge_triggered = False
                barge_evidence_ms = 0.0
                barge_last_reason = None
                barge_last_good_monotonic = None
                pre_roll.clear()
                if hasattr(vad, "reset_states"):
                    try:
                        vad.reset_states()
                    except Exception:
                        pass

            capture_ready.set()  # VAD initialized and capture worker prepared.
            try:
                while not stop_capture.is_set():
                    try:
                        chunk, block_start = mic_q.get(timeout=0.2)
                    except queue.Empty:
                        continue
                    speaking_now = bool(self.speaking)
                    processed = chunk
                    metrics = {}
                    if speaking_now:
                        if aec is not None and barge_enabled:
                            processed, metrics = aec.process(chunk, block_start)
                            last_aec_metrics = metrics
                            skipped_tts = False
                        elif not self.cfg.get("allow_barge_in_without_aec", False):
                            if not skipped_tts:
                                reset_vad_state()
                                skipped_tts = True
                            continue
                    else:
                        skipped_tts = False

                    pre_roll.append(np.asarray(processed, dtype=np.float32).copy())
                    evt = vad(processed, return_seconds=False)
                    if evt and "start" in evt:
                        speech = list(pre_roll)
                        active = True
                        current_barge = speaking_now
                        speech_started = time.monotonic()
                        barge_triggered = False
                        barge_evidence_ms = 0.0
                        barge_last_reason = None
                        barge_last_good_monotonic = None
                        if self.debug:
                            source = "aec_residual" if current_barge else "microphone"
                            print(f"[AUX] VAD speech_start source={source}")
                    elif active:
                        speech.append(np.asarray(processed, dtype=np.float32).copy())

                    if active and current_barge and not barge_triggered and speaking_now:
                        elapsed_ms = (time.monotonic() - float(speech_started or time.monotonic())) * 1000.0
                        warmup_ms = float(aec_cfg.get("warmup_ms", 350.0))
                        speaker_age_ms = (
                            (time.monotonic() - float(speaker_epoch[0])) * 1000.0
                            if speaker_epoch[0] is not None
                            else 0.0
                        )
                        if speaker_age_ms >= warmup_ms:
                            ok, why = self._barge_metrics_ok(last_aec_metrics, barge_cfg)
                            now_mono = time.monotonic()
                            if ok:
                                barge_evidence_ms += block_ms
                                barge_last_good_monotonic = now_mono
                                barge_last_reason = None
                            else:
                                # v0.6.1 required strictly consecutive good
                                # blocks. Natural word/syllable gaps therefore
                                # alternated far_end_quiet/aec_not_ready and made
                                # barge-in practically impossible. Preserve a
                                # short evidence reservoir across neutral gaps,
                                # but reset immediately on evidence that the
                                # residual is actually echo-dominated.
                                neutral = why in {
                                    "far_end_quiet",
                                    "reference_gap",
                                    "aec_not_ready",
                                    "echo_path_stale",
                                }
                                gap_tol_ms = float(barge_cfg.get("evidence_gap_tolerance_ms", 180.0))
                                gap_age_ms = (
                                    (now_mono - barge_last_good_monotonic) * 1000.0
                                    if barge_last_good_monotonic is not None
                                    else None
                                )
                                if not neutral or (gap_age_ms is not None and gap_age_ms > gap_tol_ms):
                                    barge_evidence_ms = 0.0
                                    if gap_age_ms is not None and gap_age_ms > gap_tol_ms:
                                        barge_last_good_monotonic = None
                                if self.debug and why != barge_last_reason:
                                    print(f"[AUX] barge_in=candidate rejected reason={why}")
                                barge_last_reason = why

                            evidence_required_ms = float(barge_cfg.get("evidence_ms", 160.0))
                            if (
                                elapsed_ms >= float(barge_cfg.get("confirm_ms", 240.0))
                                and barge_evidence_ms >= evidence_required_ms
                            ):
                                barge_triggered = True
                                request_barge(last_aec_metrics)

                    if evt and "end" in evt and active:
                        active = False
                        audio = np.concatenate(speech) if speech else np.empty(0, dtype=np.float32)
                        speech = []
                        was_candidate = bool(current_barge)
                        was_confirmed = bool(barge_triggered)
                        meta = {
                            "barge_in": was_confirmed,
                            "barge_candidate": was_candidate,
                            "aec": dict(last_aec_metrics),
                        }
                        current_barge = False
                        speech_started = None
                        barge_triggered = False
                        barge_evidence_ms = 0.0
                        barge_last_reason = None
                        barge_last_good_monotonic = None
                        pre_roll.clear()
                        if audio.size:
                            if was_candidate and not was_confirmed:
                                # This audio began while TALUS was speaking but
                                # never passed the double-talk gate.  Do not send
                                # likely echo through Whisper, where it can become
                                # a hallucinated wake phrase such as "TALUS Talus".
                                if self.debug:
                                    print("[AUX] barge_in=candidate discarded reason=not_confirmed")
                            else:
                                utterance_q.put((audio, meta))
            except BaseException as exc:
                utterance_q.put((None, {"error": exc}))

        capture_thread = threading.Thread(target=capture_worker, name="aux-live-capture", daemon=True)

        try:
            # STT was previously loaded lazily on the first utterance, making
            # 'models loaded' misleading. Warm it before declaring readiness.
            if hasattr(self.stt, "_load"):
                self.stt._load()
            if bool(stream_cfg.get("prewarm", True)):
                try:
                    self.tts.warmup()
                except Exception:
                    pass

            with sd.InputStream(
                samplerate=sr,
                channels=1,
                dtype="float32",
                blocksize=block,
                device=self.cfg.get("input_device"),
                callback=cb,
            ):
                capture_thread.start()
                # No input is accepted until the actual capture worker has
                # completed VAD setup AND the chosen voice has finished playing.
                # The thread publishes failures into utterance_q, so poll for
                # failure instead of indefinitely waiting on capture_ready.
                deadline = time.monotonic() + 120.0
                while not capture_ready.wait(timeout=0.1):
                    try:
                        pending_audio, pending_meta = utterance_q.get_nowait()
                    except queue.Empty:
                        pending_meta = {}
                    if pending_meta.get("error") is not None:
                        raise pending_meta["error"]
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Timed out initializing microphone VAD")
                from .startup_ready import StartupReadyGate
                gate = getattr(self.conversation, "startup_gate", None)
                if gate is None:
                    gate = StartupReadyGate(self.state)
                    self.conversation.startup_gate = gate
                self.state.component("audio", "starting")
                def play_startup_greeting(wav):
                    sink.play(wav)
                    # Draining/stopping the one-off stream avoids considering
                    # buffered speaker PCM 'played' before hardware is done.
                    # Conversation TTS will reopen the stream when required.
                    sink.close()
                    time.sleep(0.15)  # Let the room's final echo decay.

                def verify_capture_still_running():
                    if not capture_thread.is_alive():
                        raise RuntimeError("Microphone capture stopped during greeting")

                gate.announce(
                    self.tts,
                    output_device=self.cfg.get("output_device"),
                    play=play_startup_greeting,
                    verify_ready=verify_capture_still_running,
                )
                # Release capture after actual synchronous playback finishes.
                # No startup echo is admitted to the VAD queue or STT.
                capture_allowed.set()
                self.state.component("audio", "listening")
                while True:
                    audio, capture_meta = utterance_q.get()
                    if capture_meta.get("error") is not None:
                        raise capture_meta["error"]
                    if audio is None or len(audio) == 0:
                        continue
                    if self.debug:
                        duration_s = float(len(audio)) / float(sr) if sr else 0.0
                        label = "barge-in" if capture_meta.get("barge_in") else "speech"
                        print(f"[AUX] VAD speech_end duration={duration_s:.2f}s type={label}; transcribing...")
                    result = self.stt.transcribe(audio)
                    text = result.get("text", "").strip()
                    if not text:
                        if self.debug:
                            print("[AUX] STT returned no text; utterance ignored.")
                        continue
                    self._debug_stt(result)
                    if capture_meta.get("barge_in"):
                        gate_ok, gate_reason, gate_metrics = self._barge_post_stt_gate(
                            audio, result, sr, capture_meta
                        )
                    else:
                        gate_ok, gate_reason, gate_metrics = self._speech_gate(audio, result, sr)
                    self._debug_speech_gate(gate_ok, gate_reason, gate_metrics)
                    if not gate_ok:
                        if self.debug and capture_meta.get("barge_in"):
                            print(f"[AUX] barge_in=discarded_after_stt reason={gate_reason}; returning to listening")
                        try:
                            self.engagement.touch()
                        except Exception:
                            pass
                        barge_event.clear()
                        speaker_epoch[0] = None
                        continue
                    try:
                        pi_state = self.pi.state()
                    except Exception:
                        pi_state = {}
                    if capture_meta.get("barge_in"):
                        # A confirmed near-end utterance that interrupted TALUS is
                        # itself strong direct-address evidence. Do not make a user
                        # repeat the wake word merely because a long robot response
                        # outlived the ordinary engagement timer.
                        wake = self.engagement.wake_match(text) if hasattr(self.engagement, "wake_match") else None
                        try:
                            self.engagement.touch()
                        except Exception:
                            pass
                        decision = {"accept": True, "score": 1.0, "reason": "barge_in", "wake": wake}
                    else:
                        decision = self.engagement.evaluate(text, pi_state)
                        wake = decision.get("wake") if isinstance(decision, dict) else None
                    self.state.update(
                        "engagement",
                        state="engaged" if decision["accept"] else "idle",
                        score=decision["score"],
                        reason=decision["reason"],
                        wake=wake,
                    )
                    self._debug_engagement(decision)
                    if wake and self.telemetry is not None:
                        try:
                            self.telemetry.record(
                                "wake_match",
                                {
                                    "raw_alias": wake.get("raw_alias"),
                                    "canonical_target": wake.get("canonical"),
                                    "match_kind": wake.get("kind"),
                                    "detected_language": result.get("language"),
                                    "language_probability": result.get("language_probability"),
                                },
                            )
                        except Exception:
                            pass
                    if not decision["accept"]:
                        continue

                    if capture_meta.get("barge_in") and self._is_wake_only_text(text, wake=wake):
                        # Calling only TALUS's name during an answer means "stop
                        # and listen to me", not "ask Qwen to invent the next
                        # topic from conversation history".  This also contains
                        # any future wake-word hallucination even if it passes all
                        # acoustic/STT gates.
                        try:
                            self.engagement.touch()
                        except Exception:
                            pass
                        barge_event.clear()
                        speaker_epoch[0] = None
                        try:
                            reference.clear()
                        except Exception:
                            pass
                        if self.debug:
                            print("[AUX] barge_in=wake_only attention_hold; waiting for follow-up")
                        continue

                    turn_language, language_reason = self._select_turn_language(result, text, wake=wake)
                    if self.debug and turn_language != (result.get("language") or "und"):
                        print(
                            f"[AUX] language={turn_language} ({language_reason}; "
                            f"STT suggested {result.get('language') or 'und'} at "
                            f"{float(result.get('language_probability', 0.0) or 0.0):.0%})"
                        )

                    # This turn is now the active owner of the speaker.  Clear the
                    # previous interruption signal only after the barge-in audio has
                    # itself passed STT/engagement.
                    barge_event.clear()
                    speaker_epoch[0] = None
                    try:
                        reference.clear()
                    except Exception:
                        pass
                    if aec is not None:
                        try:
                            aec.begin_utterance()
                        except Exception:
                            pass
                    interrupted = False

                    if bool(stream_cfg.get("enabled", True)):
                        sink.reset_cancel()
                        sink.begin_utterance()
                        chunker = SpeechChunker(
                            first_min_chars=int(stream_cfg.get("first_chunk_min_chars", 24)),
                            min_chars=int(stream_cfg.get("min_chunk_chars", 90)),
                            max_chars=int(stream_cfg.get("max_chunk_chars", 280)),
                        )
                        def tts_worker_error(exc):
                            # Worker-thread exceptions used to disappear when no
                            # on_error callback was installed.  Errors are always
                            # surfaced; normal debug chatter remains --listen-only.
                            print(f"[AUX TTS ERROR] {type(exc).__name__}: {exc}")

                        player = StreamingTtsPlayer(
                            synthesize_wav,
                            play_wav,
                            max_queue=int(stream_cfg.get("queue_size", 8)),
                            max_audio_queue=int(stream_cfg.get("audio_queue_size", 3)),
                            # Buffer two synthesized chunks before the first word
                            # when possible.  This trades a little first-word
                            # latency for much smoother early playback on CPU TTS.
                            startup_buffer_chunks=int(stream_cfg.get("startup_buffer_chunks", 2)),
                            startup_buffer_timeout_ms=float(stream_cfg.get("startup_buffer_timeout_ms", 1800)),
                            on_error=tts_worker_error,
                            on_cancel_playback=sink.cancel,
                        )
                        with active_player_lock:
                            active_player[0] = player
                        active_speech_language = [turn_language]
                        display_started = [False]

                        def queue_tts(text_to_speak):
                            if barge_event.is_set():
                                raise BargeInInterrupt("near_end_speech")
                            for span, span_language in self.tts.segment_text_by_language(
                                text_to_speak, hint=active_speech_language[0]
                            ):
                                player.submit(span, span_language)
                                if span_language:
                                    active_speech_language[0] = span_language

                        def progress(line):
                            if barge_event.is_set():
                                return
                            if self.debug:
                                print(f"robot> {line}")
                            try:
                                queue_tts(line)
                            except BargeInInterrupt:
                                return

                        def delta(piece):
                            if barge_event.is_set():
                                raise BargeInInterrupt("near_end_speech")
                            if self.debug:
                                if not display_started[0]:
                                    print("robot> ", end="", flush=True)
                                    display_started[0] = True
                                print(piece, end="", flush=True)
                            for phrase in chunker.feed(piece):
                                queue_tts(phrase)

                        try:
                            out = self.conversation.handle_text(
                                text,
                                language=turn_language,
                                on_reasoning_wait=progress,
                                on_reply_delta=delta,
                            )
                            if barge_event.is_set():
                                raise BargeInInterrupt("near_end_speech")
                            if self.debug:
                                if display_started[0]:
                                    print()
                                elif out.get("reply"):
                                    print("robot>", out["reply"])
                            for phrase in chunker.flush():
                                queue_tts(phrase)
                            player.wait()
                            if barge_event.is_set():
                                raise BargeInInterrupt("near_end_speech")
                            self._refresh_engagement_after_reply()
                            self._debug_turn_diagnostics(out)
                        except BargeInInterrupt:
                            interrupted = True
                            player.cancel()
                            if self.debug:
                                if display_started[0]:
                                    print()
                                print("[AUX] assistant speech interrupted; listening to barge-in utterance.")
                        except BaseException:
                            player.cancel()
                            self.conversation.clear_history("live_audio_interrupted")
                            raise
                        finally:
                            with active_player_lock:
                                active_player[0] = None
                            player.close()
                            speaker_epoch[0] = None
                    else:
                        sink.reset_cancel()
                        sink.begin_utterance()

                        def progress(line):
                            if self.debug:
                                print(f"robot> {line}")
                            try:
                                wav = synthesize_wav(line, turn_language)
                                play_wav(wav)
                            except Exception as exc:
                                if self.debug:
                                    print("[AUX TTS ERROR]", exc)

                        out = self.conversation.handle_text(
                            text,
                            language=turn_language,
                            on_reasoning_wait=progress,
                        )
                        if self.debug and out.get("reply"):
                            print("robot>", out["reply"])
                        wav = synthesize_wav(out["reply"], out.get("language") or turn_language)
                        play_wav(wav)
                        if not barge_event.is_set():
                            self._refresh_engagement_after_reply()
                            self._debug_turn_diagnostics(out)
                        speaker_epoch[0] = None

                    if interrupted:
                        # The capture thread keeps running and will enqueue the
                        # completed near-end utterance.  Loop immediately and wait
                        # for it instead of terminating the live session.
                        continue
        except KeyboardInterrupt:
            # Ctrl+C is an intentional operator shutdown, not an audio failure.
            sink.cancel()
            self.conversation.clear_history("keyboard_interrupt")
            raise
        except BaseException as exc:
            sink.cancel()
            self.conversation.clear_history("audio_loop_interrupted")
            print(f"[AUX AUDIO FATAL] {type(exc).__name__}: {exc}")
            raise
        finally:
            stop_capture.set()
            try:
                mic_q.put_nowait((np.zeros(block, dtype=np.float32), time.monotonic()))
            except Exception:
                pass
            if capture_thread.is_alive():
                capture_thread.join(timeout=2.0)
            sink.close()
