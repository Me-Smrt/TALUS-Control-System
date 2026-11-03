from __future__ import annotations

import argparse
import time
from pathlib import Path

from aux_core.api_server import AuxApiServer
from aux_core.audio_loop import AudioConversationLoop
from aux_core.audio_output import ContinuousWavPlayer, play_wav_bytes
from aux_core.config import load_json, resolve_path
from aux_core.conversation import ConversationManager
from aux_core.engagement import EngagementManager
from aux_core.face_identity import SFaceIdentityBackend
from aux_core.knowledge import LocalKnowledgeBase
from aux_core.llm import MockLlm, OpenAICompatibleLlm
from aux_core.llm_server import ManagedLlamaServer
from aux_core.pi_client import PiClient, PiLinkMonitor
from aux_core.prompt_context import build_runtime_system_context
from aux_core.people import PersonStore
from aux_core.person_session import PersonSessionManager
from aux_core.scheduler import PriorityScheduler
from aux_core.speech_stream import SpeechChunker, StreamingTtsPlayer
from aux_core.startup_ready import StartupReadyGate
from aux_core.language import requested_response_language
from aux_core.state import AuxiliaryState
from aux_core.status_monitor import ComponentStatusMonitor
from aux_core.stt import FasterWhisperStt
from aux_core.telemetry import TelemetryStore
from aux_core.tts import NoSpeakableText, TtsManager, VoiceSetUnavailable
from aux_core.vision import NullDetector, UltralyticsDetector
from aux_core.world_state import WorldState, WorldObserver
from aux_core.engineering import EngineeringKnowledgeBase
from aux_core.voices import VoiceRegistry

ROOT = Path(__file__).resolve().parent


def args():
    p = argparse.ArgumentParser(description="Automaton auxiliary cognition R&D service")
    p.add_argument("--config", type=Path, default=ROOT / "config/default.json")
    p.add_argument("--voices", type=Path, default=ROOT / "config/voices.json")
    p.add_argument(
        "--console",
        "--text-console",
        dest="console",
        action="store_true",
        help="Type directly to the real LLM in the terminal; bypasses microphone/VAD/STT",
    )
    p.add_argument("--listen", action="store_true", help="Run the real microphone/VAD/STT conversation loop")
    p.add_argument("--speak", action="store_true", help="With --console, synthesize and play robot replies and deep-thinking cues")
    p.add_argument("--mock-llm", action="store_true", help="Use the mock LLM and do not start llama.cpp")
    p.add_argument("--no-llm-server", action="store_true", help="Require an already-running OpenAI-compatible endpoint")
    p.add_argument("--no-api", action="store_true")
    return p.parse_args()


def main():
    a = args()
    # Explicit developer modes are intentionally verbose.  Bare `python main.py`
    # is the deployment entrypoint and keeps stdout quiet unless something is
    # actually wrong.
    developer_terminal = bool(a.console or a.listen)

    def info(message: str) -> None:
        if developer_terminal:
            print(message)

    cfg = load_json(a.config)
    state = AuxiliaryState(cfg["service"].get("version", "0.3.0"))
    pi = PiClient(cfg["pi"])

    runtime = resolve_path(ROOT, cfg["tts"].get("runtime_path", "runtime/tts_state.json"))
    voices = VoiceRegistry(a.voices, runtime, cfg["tts"]["default_voice_id"])
    tts = TtsManager(cfg["tts"], voices, ROOT)
    knowledge = LocalKnowledgeBase(cfg.get("knowledge", {}), ROOT)
    telemetry = TelemetryStore(cfg.get("telemetry", {}), ROOT)
    runtime_system_context = build_runtime_system_context(ROOT, cfg, tts=tts, voices=voices)
    installed_voice_count = sum(1 for voice in tts.list_voices() if voice.get("available"))
    info(f"[AUX] System prompt runtime inventory: {installed_voice_count} installed TTS voice(s) detected.")

    managed_llm = None
    if a.mock_llm:
        llm = MockLlm()
    else:
        managed_llm = ManagedLlamaServer(ROOT, cfg["llm"])
        if not a.no_llm_server:
            mode = managed_llm.ensure_ready(verbose=developer_terminal)
            info(f"[AUX] LLM server ready at {cfg['llm']['base_url']} ({mode}).")
        elif not managed_llm.healthy():
            raise RuntimeError(f"No LLM server is responding at {managed_llm.health_url}")
        llm = OpenAICompatibleLlm(cfg["llm"], ROOT, runtime_system_context=runtime_system_context)

    detector = (
        UltralyticsDetector(cfg["vision"]["detector"], ROOT)
        if cfg["vision"]["detector"].get("enabled", True)
        else NullDetector()
    )
    scheduler = (
        PriorityScheduler(int(cfg.get("scheduler", {}).get("max_queue", 32)))
        if cfg.get("scheduler", {}).get("enabled", True)
        else None
    )
    conv_cfg = dict(cfg["conversation"])
    conv_cfg["history_turns"] = cfg["llm"].get("history_turns", 8)
    stt = FasterWhisperStt(cfg["stt"], ROOT)
    eng = EngagementManager(cfg["engagement"])
    people_store = PersonStore(cfg.get("people", {}), ROOT)
    identity = SFaceIdentityBackend(cfg.get("identity", {}), ROOT)
    conversation = ConversationManager(conv_cfg, llm, pi, detector, tts, state, scheduler, knowledge, telemetry=telemetry)
    world_cfg = cfg.get("world_state", {})
    world = WorldState(current_ms=world_cfg.get("current_ms", 2500),
                       retention_ms=world_cfg.get("retention_ms", 15000),
                       max_tracks=world_cfg.get("max_tracks", 40))
    conversation.world = world
    conversation.engineering_knowledge = EngineeringKnowledgeBase(cfg.get("engineering_knowledge", {"database_path": "runtime/engineering.sqlite3"}), ROOT)
    world_observer = WorldObserver(pi, detector, world, period_s=world_cfg.get("poll_period_s", 1.5))

    # TALUS STARTUP READY CUE: gate API/console until speech ends.
    startup_gate = StartupReadyGate(state)
    conversation.startup_gate = startup_gate
    world_observer.ready_predicate = lambda: startup_gate.ready
    person_session = PersonSessionManager(
        cfg.get("people", {}), pi, people_store, identity, state,
        conversation=conversation, engagement=eng,
    )
    conversation.person_session = person_session
    api = None
    audio_sink = None
    pi_link_monitor = None
    component_monitor = None

    def synthesize_wav(text: str, language: str | None = None) -> bytes:
        wav, _voice = tts.synthesize(text, language=language)
        return wav

    def report_tts_error(exc: Exception) -> None:
        # Formatting-only fragments can appear at streaming chunk boundaries.
        # They are intentionally dropped rather than logged as backend failures.
        if isinstance(exc, NoSpeakableText):
            return
        if isinstance(exc, VoiceSetUnavailable):
            info(
                f"\n[AUX] TTS skipped {exc.language}: voice set "
                f"{exc.voice_set_id!r} has no installed matching voice. "
                "Choose Best available (mixed) to allow cross-set fallback."
            )
            return
        # Unexpected TTS failures remain visible even in deployment mode.
        print("\n[AUX TTS ERROR]", exc)

    def speak_text(text: str, *, language: str | None = None) -> None:
        wav = synthesize_wav(text, language)
        if audio_sink is not None:
            audio_sink.play(wav)
        else:
            play_wav_bytes(wav, output_device=cfg.get("audio", {}).get("output_device"))

    def submit_language_aware(player: StreamingTtsPlayer, text: str, language: str | None = None) -> None:
        for span, span_language in tts.segment_text_by_language(text, hint=language):
            player.submit(span, span_language)

    try:
        def publish_pi_link(status: str, detail: str | None) -> None:
            state.component("pi_link", status)
            if status == "online":
                info(f"[AUX] Pi link online at {pi.base}")
            else:
                suffix = f": {detail}" if detail else ""
                info(f"[AUX] Pi link offline at {pi.base}{suffix}")

        pi_link_monitor = PiLinkMonitor(
            pi,
            publish_pi_link,
            period_s=float(cfg.get("pi", {}).get("link_probe_period_s", 2.0)),
        )
        pi_link_monitor.start()
        if bool(world_cfg.get("enabled", True)):
            world_observer.start()

        state.component("stt", "ready" if stt.available() else "model_missing")
        state.component("vision", "ready" if detector.available() else "model_missing")
        try:
            current, _current_backend = tts._select_voice("en")
            tts_ready = True
        except Exception:
            current = voices.get()
            tts_ready = tts.voice_status(current)
        state.update(
            "voice",
            active_id=current["id"],
            active_set_id=voices.active_set_id,
            backend=current.get("backend"),
            available=tts_ready,
        )
        state.component("tts", "ready" if tts_ready else "dependency_or_model_missing")
        if a.speak and tts_ready:
            stream_cfg = cfg.get("tts", {}).get("streaming", {})
            if bool(stream_cfg.get("prewarm", True)):
                info("[AUX] Warming TTS backend so the first spoken chunk does not pay model-load latency...")
                tts.warmup(language="en")
            audio_sink = ContinuousWavPlayer(
                output_device=cfg.get("audio", {}).get("output_device"),
                trim_silence=bool(stream_cfg.get("trim_chunk_silence", True)),
                leading_silence_ms=float(stream_cfg.get("leading_silence_ms", 20)),
                trailing_silence_ms=float(stream_cfg.get("trailing_silence_ms", 70)),
                first_preroll_ms=float(stream_cfg.get("first_preroll_ms", 180)),
            )
        state.component("llm", "configured" if not a.mock_llm else "mock")
        kb_status = knowledge.status()
        state.component("knowledge", "ready" if kb_status.get("available") else "database_missing")
        state.update("knowledge", **kb_status)
        state.update("telemetry", **telemetry.snapshot())
        identity_status = identity.status()
        state.component("identity", "ready" if identity_status.get("available") else "model_missing")

        # Keep every operator-facing component status fresh. The dashboard itself
        # already polls /v1/status; this monitor ensures the fields behind that
        # endpoint are not startup-only snapshots.
        component_monitor = ComponentStatusMonitor(
            state.component,
            {
                "llm": lambda: "mock" if a.mock_llm else (
                    "ready" if managed_llm is not None and managed_llm.healthy() else "offline"
                ),
                "stt": lambda: "ready" if stt.available() else "model_missing",
                "vision": lambda: "ready" if detector.available() else "model_missing",
                "tts": lambda: "ready" if tts.voice_status(voices.get()) else "dependency_or_model_missing",
                "knowledge": lambda: "ready" if knowledge.available() else "database_missing",
                "identity": lambda: "ready" if identity.available() else "model_missing",
            },
            period_s=float(cfg.get("service", {}).get("status_probe_period_s", 2.0)),
        )
        component_monitor.start()

        person_session.start()
        state.update(status="online")

        if not a.no_api:
            api = AuxApiServer(cfg["service"], state, tts, voices, conversation, knowledge=knowledge, person_session=person_session, telemetry=telemetry)
            api.start()
            info(f"[AUX] API http://{api.host}:{api.port}/v1/status")

        info("[AUX] Models are never downloaded automatically by this project. See docs/MODELS.md.")
        if not tts_ready:
            info("[AUX] TTS is not ready. If local voice assets are present, run: pip install -r requirements.txt")
        if not kb_status.get("available"):
            info("[AUX] Local knowledge DB not built yet. See knowledge/README.md.")
        if not identity_status.get("available"):
            info("[AUX] Face-presence session reset is active, but persistent face recognition is unavailable until the optional YuNet/SFace models are installed. See docs/PERSON_IDENTITY.md.")

        # Spoken in non-microphone modes; a live loop announces after capture is ready.
        if not a.listen and (a.console or not cfg.get("audio", {}).get("enabled", False)):
            startup_gate.announce(tts, output_device=cfg.get("audio", {}).get("output_device"))
        if a.listen:
            if not cfg.get("audio", {}).get("enabled", False):
                raise RuntimeError("Enable audio.enabled in config before using --listen")
            loop = AudioConversationLoop(
                cfg["audio"], stt, eng, conversation, tts, pi, state,
                telemetry=telemetry, debug=True,
            )
            loop.run()

        elif a.console:
            print("[AUX] Direct text console: microphone/VAD/STT are bypassed.")
            print("[AUX] /quit exits. /clear forgets conversation history. /vision <q> forces one frame. /observe <q> forces a temporal observation. /say <text> tests TTS.")
            print("[AUX] /think <q> forces deep reasoning. /fast <q> forces the low-latency profile.")
            print("[AUX] /who shows the active person. /enroll <name> saves the current face. /remember <text> saves a bounded personal memory. /forget-person deletes the active person.")
            if a.speak:
                print("[AUX] --speak enabled: final replies and deep-thinking progress cues will be voiced.")

            while True:
                try:
                    text = input("you> ").strip()
                except EOFError:
                    conversation.clear_history("console_eof")
                    break
                if text in {"/quit", "/exit"}:
                    conversation.clear_history("console_exit")
                    break
                if text == "/clear":
                    conversation.clear_history("manual_clear")
                    print("[AUX] Conversation history cleared.")
                    continue
                if not text:
                    continue

                if text == "/who":
                    person = person_session.current_person()
                    if person:
                        print(f"[AUX] Active person: {person['name']} ({person['person_id']})")
                    else:
                        print("[AUX] No enrolled person is currently recognized.")
                    continue
                if text.startswith("/enroll "):
                    name = text[8:].strip()
                    try:
                        person = person_session.enroll_current(name)
                        print(f"[AUX] Enrolled/updated {person['name']} ({person['person_id']}). Conversation context was reset.")
                    except Exception as exc:
                        print("[AUX IDENTITY ERROR]", exc)
                    continue
                if text.startswith("/remember "):
                    memory = text[10:].strip()
                    try:
                        saved = person_session.remember_current(memory)
                        print(f"[AUX] Remembered for {saved['name']}: {saved['text']}")
                    except Exception as exc:
                        print("[AUX MEMORY ERROR]", exc)
                    continue
                if text == "/forget-person":
                    if person_session.forget_current():
                        print("[AUX] Active person and their stored memories were deleted; conversation context cleared.")
                    else:
                        print("[AUX] No active enrolled person to forget.")
                    continue

                if text.startswith("/say "):
                    sample = text[5:].strip()
                    if not sample:
                        print("[AUX ERROR] /say requires text")
                        continue
                    try:
                        segments = tts.segment_text_by_language(sample)
                        if audio_sink is not None:
                            audio_sink.begin_utterance()
                        for span, span_language in segments:
                            wav, used_voice = tts.synthesize(span, language=span_language)
                            print(
                                f"[AUX] TTS route: {used_voice.get('language', 'und')} "
                                f"via {used_voice['id']}"
                            )
                            if audio_sink is not None:
                                audio_sink.play(wav)
                            else:
                                play_wav_bytes(wav, output_device=cfg.get("audio", {}).get("output_device"))
                    except Exception as e:
                        print("[AUX TTS ERROR]", e)
                    continue

                requested_reasoning = None
                if text.startswith("/think "):
                    requested_reasoning = "deep"
                    text = text[7:].strip()
                elif text.startswith("/fast "):
                    requested_reasoning = "fast"
                    text = text[6:].strip()

                force_temporal_vision = text.startswith("/observe ")
                if force_temporal_vision:
                    text = text[9:].strip()
                force_vision = text.startswith("/vision ")
                text = text[8:].strip() if force_vision else text
                if not text:
                    print("[AUX ERROR] A question is required")
                    continue

                # Establish one active language for the turn. Console text has no
                # STT metadata, so detect the user utterance once and use it as
                # hysteresis for streamed TTS routing. This prevents tiny English
                # checklist/UI fragments from independently jumping into another
                # Latin-script voice while still allowing strong language/script
                # changes to switch normally.
                interaction_language = tts.resolve_language(text, hint=None) or "en"
                requested_speech_language = requested_response_language(text)
                active_speech_language = requested_speech_language or interaction_language

                # If the user explicitly asks for a different output language,
                # warm that route before generation starts. This avoids making
                # the first translated sentence pay one-time Kokoro/pipeline load
                # cost and gives the streaming router the correct language prior
                # from chunk one. Piper warmup is effectively a cheap availability
                # check, so this remains safe on the Linux target as well.
                if a.speak and requested_speech_language:
                    try:
                        tts.warmup(language=requested_speech_language)
                    except Exception as exc:
                        report_tts_error(exc)

                # Stream final-answer text to the terminal.  With --speak,
                # sentence-sized chunks are also queued to TTS so generation,
                # synthesis, and playback can overlap instead of waiting for the
                # entire response to finish first.
                stream_cfg = cfg.get("tts", {}).get("streaming", {})
                chunker = SpeechChunker(
                    first_min_chars=int(stream_cfg.get("first_chunk_min_chars", 24)),
                    first_max_chars=int(stream_cfg.get("first_chunk_max_chars", 140)),
                    min_chars=int(stream_cfg.get("min_chunk_chars", 90)),
                    max_chars=int(stream_cfg.get("max_chunk_chars", 280)),
                )
                player = None
                if a.speak and bool(stream_cfg.get("enabled", True)):
                    if audio_sink is not None:
                        audio_sink.reset_cancel()
                        audio_sink.begin_utterance()
                    player = StreamingTtsPlayer(
                        synthesize_wav,
                        audio_sink.play if audio_sink is not None else lambda wav: play_wav_bytes(
                            wav, output_device=cfg.get("audio", {}).get("output_device")
                        ),
                        max_queue=int(stream_cfg.get("queue_size", 8)),
                        max_audio_queue=int(stream_cfg.get("audio_queue_size", 3)),
                        on_error=report_tts_error,
                        on_cancel_playback=audio_sink.cancel if audio_sink is not None else None,
                    )
                elif a.speak and audio_sink is not None:
                    audio_sink.reset_cancel()
                    audio_sink.begin_utterance()

                display_started = False

                def queue_tts(text_to_speak: str) -> None:
                    nonlocal active_speech_language
                    if player is None:
                        return
                    for span, span_language in tts.segment_text_by_language(
                        text_to_speak, hint=active_speech_language
                    ):
                        player.submit(span, span_language)
                        if span_language:
                            active_speech_language = span_language

                def progress(line: str) -> None:
                    # Deep-reasoning status lines precede the final answer and
                    # use the same serialized playback queue when speech is on.
                    print(f"robot> {line}")
                    if player is not None:
                        queue_tts(line)
                    elif a.speak:
                        try:
                            speak_text(line)
                        except Exception as exc:
                            print("[AUX TTS ERROR]", exc)

                def reply_delta(delta: str) -> None:
                    nonlocal display_started
                    if not display_started:
                        print("robot> ", end="", flush=True)
                        display_started = True
                    print(delta, end="", flush=True)
                    if player is not None:
                        for phrase in chunker.feed(delta):
                            queue_tts(phrase)

                try:
                    out = conversation.handle_text(
                        text,
                        language=interaction_language,
                        force_vision=force_vision,
                        force_temporal_vision=force_temporal_vision,
                        reasoning_mode=requested_reasoning,
                        on_reasoning_wait=progress,
                        on_reply_delta=reply_delta,
                    )
                    if display_started:
                        print()
                    reply = out["reply"]
                    if not display_started:
                        print("robot>", reply)

                    if player is not None:
                        # The final turn language becomes the fallback for any
                        # buffered tail, but the routing session otherwise keeps
                        # the language selected by prior streamed spans.
                        if out.get("language") and active_speech_language is None:
                            active_speech_language = out.get("language")
                        for phrase in chunker.flush():
                            queue_tts(phrase)
                        player.wait()
                    elif a.speak and reply:
                        # Streaming can be disabled in config for A/B comparison.
                        try:
                            speak_text(reply, language=out.get("language"))
                        except Exception as exc:
                            print("[AUX TTS ERROR]", exc)

                    print(f"[AUX] reasoning={out['reasoning_mode']} ({out['reasoning_reason']}; score={out.get('reasoning_score', 0):.2f})")
                    if out.get("verification_used"):
                        print("[AUX] verification=quantitative_second_pass")
                    if out.get("knowledge_sources"):
                        names = ", ".join(x["source_id"] for x in out["knowledge_sources"][:5])
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
                except KeyboardInterrupt:
                    if player is not None:
                        player.cancel()
                    elif audio_sink is not None:
                        audio_sink.cancel()
                    conversation.clear_history("keyboard_interrupt")
                    if display_started:
                        print()
                    print("[AUX] Interrupted; conversation history cleared.")
                    raise
                except Exception as e:
                    if player is not None:
                        player.cancel()
                    conversation.clear_history("turn_aborted")
                    if display_started:
                        print()
                    print("[AUX ERROR]", e)
                    print("[AUX] Aborted turn; conversation history cleared.")
                finally:
                    if player is not None:
                        player.close()
        else:
            # Deployment mode: run the real audio conversation loop when audio
            # is enabled, but keep routine operator/debug chatter off stdout.
            # If audio is intentionally disabled, remain available as a quiet
            # API/service process exactly as earlier revisions did.
            if cfg.get("audio", {}).get("enabled", False):
                loop = AudioConversationLoop(
                    cfg["audio"], stt, eng, conversation, tts, pi, state,
                    telemetry=telemetry, debug=False,
                )
                loop.run()
            else:
                while True:
                    time.sleep(1)

    except KeyboardInterrupt:
        conversation.clear_history("keyboard_interrupt")
    finally:
        world_observer.stop()
        if component_monitor is not None:
            component_monitor.stop()
        if pi_link_monitor is not None:
            pi_link_monitor.stop()
        conversation.clear_history("shutdown")
        try:
            person_session.stop()
        except Exception:
            pass
        if audio_sink is not None:
            try:
                audio_sink.close()
            except Exception:
                pass
        try:
            if api:
                api.stop()
        except BaseException:
            # A second Ctrl+C during shutdown should never turn a normal
            # operator exit into a traceback/fatal-looking failure.
            pass
        if scheduler:
            scheduler.close()
        if managed_llm:
            managed_llm.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
