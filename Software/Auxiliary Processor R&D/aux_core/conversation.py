from __future__ import annotations

import time
import threading
from datetime import datetime, timezone
from collections import deque
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import Any, Callable

from .reasoning import ReasoningDecision, ReasoningPolicy, ThinkingCueSequence
from .action_router import InteractionActionRouter
from .language import detect_text_language, requested_response_language
from .util import language_family
from .output_guard import clean_visible_answer
from .temporal_vision import build_contact_sheet, summarize_motion
from .engineering import wye_delta_reference


class ConversationManager:
    def __init__(self, cfg, llm, pi, detector, tts, state, scheduler=None, knowledge=None, person_session=None, telemetry=None):
        self.cfg = cfg
        self.llm = llm
        self.pi = pi
        self.detector = detector
        self.tts = tts
        self.state = state
        self.scheduler = scheduler
        self.knowledge = knowledge
        self.person_session = person_session
        self.telemetry = telemetry
        self.world = None
        self.engineering_knowledge = None
        self.history = deque(maxlen=max(2, int(cfg.get("history_turns", 8)) * 2))
        self._history_lock = threading.RLock()
        self._reset_epoch = 0
        self.reasoning = ReasoningPolicy(cfg.get("reasoning", {}))
        self.cues = ThinkingCueSequence(cfg.get("reasoning", {}))
        self.action_router = InteractionActionRouter(cfg.get("action_router", {}))

    def _visual_hint(self, text, language=None):
        low = text.casefold()
        family = language_family(language)
        kws = self.cfg.get("visual_keywords", {})
        candidates = list(kws.get(family, [])) + list(kws.get("en", []))
        return any(k.casefold() in low for k in candidates)

    def _messages(self, text):
        with self._history_lock:
            prior = list(self.history)
        return prior + [{"role": "user", "content": text}]

    def clear_history(self, reason: str = "manual_reset") -> None:
        """Forget all conversational context and reset public conversation state.

        Conversation history is intentionally in-memory only.  This method is
        called for explicit resets and every controlled interruption path so an
        aborted/stale turn cannot influence the next interaction.
        """
        with self._history_lock:
            self.history.clear()
            self._reset_epoch += 1
        self.state.update(
            "conversation",
            state="idle",
            language=None,
            last_user_text=None,
            last_reply_text=None,
            last_turn_ms=None,
            history_messages=0,
            reset_reason=str(reason),
        )

    def history_size(self) -> int:
        with self._history_lock:
            return len(self.history)

    def _run_with_progress(self, fn, mode: str, on_wait: Callable[[str], None] | None):
        if mode != "deep" or on_wait is None:
            if self.scheduler:
                return self.scheduler.submit(30, fn).result()
            return fn()

        owned_pool = None
        if self.scheduler:
            future = self.scheduler.submit(30, fn)
        else:
            owned_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="aux-deep-reasoning")
            future = owned_pool.submit(fn)

        started = time.monotonic()
        try:
            for target_s, line in self.cues.schedule(min_initial_s=6.0, min_repeat_s=15.0):
                remaining = target_s - (time.monotonic() - started)
                if remaining > 0:
                    try:
                        return future.result(timeout=remaining)
                    except FutureTimeout:
                        pass
                if future.done():
                    return future.result()
                try:
                    on_wait(line)
                except Exception:
                    # A failed progress cue (for example unavailable TTS) must
                    # never cancel the real answer.
                    pass
            # The original implementation stopped emitting cues after the finite
            # schedule and then waited forever-looking on future.result(). Continue
            # with a deliberately sparse heartbeat so a legitimately slow deep turn
            # can never look silently frozen. The underlying LLM HTTP timeout remains
            # the hard execution bound.
            heartbeat_s = max(30.0, float(getattr(self.cues, "repeat_wait_s", 15.0)) * 2.0)
            while True:
                try:
                    return future.result(timeout=heartbeat_s)
                except FutureTimeout:
                    try:
                        on_wait("I'm still working on it.")
                    except Exception:
                        pass
        finally:
            if owned_pool is not None:
                owned_pool.shutdown(wait=True)

    @staticmethod
    def _verification_messages(messages: list[dict[str, Any]], draft: str) -> list[dict[str, Any]]:
        """Build a private quantitative verification pass.

        The draft is never shown/spoken before this pass completes. The verifier
        gets the original conversational context plus the draft and is told to
        return *only* a polished final answer. This prevents visible scratch-work
        such as "Wait, that's not right" from leaking into TALUS speech.
        """
        return list(messages) + [
            {"role": "assistant", "content": draft},
            {
                "role": "user",
                "content": (
                    "Privately verify the previous answer before it is presented to the user. "
                    "Check the governing formula or method, variable/node mapping, units, arithmetic, and final numerical values. "
                    "If the problem statement is ambiguous, state the minimum necessary assumption instead of inventing a mapping. "
                    "Correct any mistake you find. Return only the final polished answer for the original user question. "
                    "Do not mention this verification step, the draft, hidden reasoning, false starts, or self-corrections. "
                    "Do not say phrases such as 'wait', 'actually', 'that's not right', 'let me restart', or 'let me be precise' as narration."
                ),
            },
        ]

    def handle_text(
        self,
        text: str,
        *,
        language: str | None = None,
        force_vision: bool = False,
        force_temporal_vision: bool = False,
        camera_id: str | None = None,
        reasoning_mode: str | None = None,
        on_reasoning_wait: Callable[[str], None] | None = None,
        on_reply_delta: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        # Fail closed while the startup greeting is being spoken. This also
        # protects API requests that arrive before the console/audio loop opens.
        gate = getattr(self, "startup_gate", None)
        if gate is not None:
            gate.require_ready()
        started = time.perf_counter()
        if hasattr(self.llm, "begin_turn_metrics"):
            try:
                self.llm.begin_turn_metrics()
            except Exception:
                pass

        # Console/API text may not arrive with an STT language code. Detect the
        # current user turn before building the LLM prompt so stale multilingual
        # history/last-topic memory cannot pull a simple English greeting into a
        # previously used language. Explicit caller language still wins.
        if not language:
            try:
                detected_language, _ = detect_text_language(text)
                language = detected_language or language
            except Exception:
                pass

        requested_reply_language = requested_response_language(text)

        # Process person/identity onboarding before snapshotting the reset epoch.
        # Enrollment is allowed to clear stale anonymous history; the current
        # turn then starts from the post-action epoch and can complete normally.
        onboarding_result = None
        if self.person_session is not None:
            try:
                onboarding_result = self.person_session.process_user_text(text)
            except Exception:
                onboarding_result = None

        with self._history_lock:
            turn_epoch = self._reset_epoch
        decision = self.reasoning.choose(text, reasoning_mode)
        action_decision = self.action_router.route(
            text,
            language=language,
            force_vision=force_vision,
            force_temporal_vision=force_temporal_vision,
            visual_keywords=self.cfg.get("visual_keywords", {}),
        )
        # Temporal perception and robot-behavior planning benefit from the buffered
        # deep-reasoning path, but an explicit /fast remains a user override.
        if action_decision.requires_deep and reasoning_mode != "fast" and decision.mode != "deep":
            decision = ReasoningDecision(
                "deep",
                action_decision.visual_reason or "behavior_planning",
                max(float(decision.score), 3.0),
                verification_required=False,
            )
        visual = action_decision.use_vision
        image = None
        objects = []
        used_camera = None
        observation_manifest = None
        observation_received_mono = None
        observation_received_utc = None
        temporal_samples = 0
        temporal_duration_ms = None
        behavior_result = None
        prompt_parts: list[str] = []
        if language:
            prompt_parts.append(
                "[Current interaction language]\n"
                f"The current user turn is detected as {language}. Reply in that language unless "
                "the user explicitly asks you to answer in another language."
            )
        if requested_reply_language:
            prompt_parts.append(
                "[Explicit response language]\n"
                f"The user explicitly requested the response in {requested_reply_language}. "
                "Answer only in that requested language unless the user also explicitly requests "
                "multiple languages. Do not prepend earlier translations or repeat the same answer "
                "in other languages."
            )

        # Identity/personal memory is intentionally separate from the institutional
        # knowledge base.  Only an actively recognized person gets this context,
        # and only details explicitly saved for that person are persisted.
        personal_memory_result = None
        current_person = None
        if self.person_session is not None:
            try:
                current_person = self.person_session.current_person()
                person_context = self.person_session.prompt_context()
                if person_context:
                    prompt_parts.append(person_context)
                if onboarding_result and onboarding_result.get("prompt_context"):
                    prompt_parts.append(str(onboarding_result["prompt_context"]))
                personal_memory_result = self.person_session.maybe_remember(text)
                if personal_memory_result:
                    if personal_memory_result.get("saved"):
                        prompt_parts.append(
                            "[Memory action]\n"
                            "The user explicitly asked you to remember something, and it has been saved locally for "
                            f"{personal_memory_result.get('name', 'the recognized person')}: "
                            f"{personal_memory_result.get('text', '')}. Acknowledge this naturally and briefly."
                        )
                    else:
                        prompt_parts.append(
                            "[Memory action]\n"
                            "The user asked you to remember something, but no recognized person is active. "
                            "Do not claim that it was saved; explain that persistent personal memory requires an enrolled recognized person."
                        )
            except Exception:
                personal_memory_result = None

        # Retrieve curated offline knowledge for every substantive turn.  FTS5
        # returns no hits for unrelated small-talk, so this remains cheap and
        # avoids brittle hard-coded trigger phrases like "TTU".
        knowledge_hits = []
        knowledge_diag = {"attempted": False, "intents": [], "query_terms": []}
        knowledge_started = time.perf_counter()
        if self.knowledge is not None:
            try:
                if hasattr(self.knowledge, "query_diagnostics"):
                    knowledge_diag = self.knowledge.query_diagnostics(text)
                knowledge_hits = self.knowledge.retrieve(text)
                kb_context = self.knowledge.format_context(knowledge_hits)
                if kb_context:
                    prompt_parts.append(kb_context)
                elif knowledge_diag.get("attempted"):
                    # A campus-specific lookup was appropriate, but the curated
                    # archive had no relevant excerpt. Ground that absence
                    # explicitly so the LLM cannot turn pretrained associations
                    # into invented Tennessee Tech services/locations while
                    # claiming the local knowledge base supports them.
                    prompt_parts.append(
                        "[Local knowledge lookup]\n"
                        "A Tennessee Tech local-knowledge lookup was attempted for this request, "
                        "but no relevant curated excerpt was found. Do not claim that the local "
                        "knowledge base says or confirms an institution-specific fact. Do not "
                        "invent campus locations, services, hours, prices, contacts, or policies. "
                        "State that the offline knowledge base does not contain enough relevant "
                        "information when the answer depends on those facts."
                    )
            except Exception:
                knowledge_hits = []
        # Engineering retrieval is a separate scope: never contaminate the
        # Tennessee Tech corpus with unrelated electronics snippets.
        engineering_reference = wye_delta_reference(text)
        if engineering_reference:
            prompt_parts.append(engineering_reference)
        if self.engineering_knowledge is not None:
            try:
                technical_hits = self.engineering_knowledge.retrieve(text)
                if technical_hits:
                    prompt_parts.append(self.engineering_knowledge.format_context(technical_hits))
            except Exception:
                pass
        knowledge_ms = (time.perf_counter() - knowledge_started) * 1000.0

        vision_ms = None
        detector_ms = None
        if visual:
            vision_started = time.perf_counter()
            frame_error = None
            detector_error = None
            temporal_error = None
            latest_raw_frame = None
            try:
                if action_decision.temporal_vision:
                    temporal_cfg = dict(self.cfg.get("temporal_vision", {}))
                    duration_ms = int(temporal_cfg.get("duration_ms", 1600))
                    samples = int(temporal_cfg.get("samples", 5))
                    max_width = int(temporal_cfg.get("max_width", 640))
                    try:
                        print(f"[AUX] capturing temporal observation: {samples} frame(s) over {duration_ms} ms...")
                        observation = self.pi.observe(
                            camera_id,
                            duration_ms=duration_ms,
                            samples=samples,
                            view="raw",
                            max_width=max_width,
                        )
                        observation_manifest = dict(observation.get("manifest") or {})
                        sampled_frames = list(observation.get("frames") or [])
                        if not sampled_frames:
                            raise RuntimeError("Pi returned a temporal observation with no image frames")
                        tile_width = int(temporal_cfg.get("contact_sheet_tile_width", 280))
                        max_columns = int(temporal_cfg.get("contact_sheet_columns", 3))
                        image = build_contact_sheet(
                            sampled_frames,
                            observation_manifest,
                            tile_width=max(180, min(420, tile_width)),
                            max_columns=max(1, min(4, max_columns)),
                        )
                        if not image:
                            raise ValueError("Temporal observation produced an empty contact sheet")
                        observation_received_mono = time.monotonic()
                        observation_received_utc = datetime.now(timezone.utc).isoformat()
                        latest_raw_frame = sampled_frames[-1]
                        used_camera = (
                            observation_manifest.get("camera_id")
                            or camera_id
                            or self.pi.choose_camera()
                        )
                        temporal_samples = len(sampled_frames)
                        temporal_duration_ms = observation_manifest.get("actual_duration_ms")
                        print(
                            f"[AUX] temporal observation ready: {temporal_samples} frame(s) "
                            f"over {temporal_duration_ms or 0} ms; preparing visual analysis."
                        )
                        prompt_parts.append(
                            "[Temporal visual observation]\n"
                            "The supplied image is a chronological contact sheet. Read it left-to-right, "
                            "then top-to-bottom; each tile is labeled with its sample time. Compare the "
                            "frames to reason about motion rather than treating them as one simultaneous scene.\n"
                            + summarize_motion(observation_manifest)
                        )
                    except Exception as e:
                        temporal_error = e
                        print(f"[AUX] temporal observation unavailable: {e}")
                        # Backward-compatible fallback for an older/unavailable Pi API.
                        # A single frame may answer static details, but it is explicitly
                        # not enough evidence for a motion claim.
                        try:
                            latest_raw_frame, headers = self.pi.frame(camera_id, view="raw")
                            if not latest_raw_frame:
                                raise ValueError("Pi returned an empty camera frame")
                            image = latest_raw_frame
                            observation_received_mono = time.monotonic()
                            observation_received_utc = datetime.now(timezone.utc).isoformat()
                            used_camera = headers.get("X-Automaton-Camera") or camera_id or self.pi.choose_camera()
                            prompt_parts.append(
                                "[Temporal visual observation unavailable]\n"
                                "Only one current image could be obtained. Do not infer dancing, waving, "
                                "direction of motion, repetition, or another temporal activity from this "
                                "single frame. Explain that a temporal observation could not be completed "
                                "if the user's question depends on motion."
                            )
                        except Exception as frame_exc:
                            frame_error = frame_exc
                            image = None
                            latest_raw_frame = None
                            print(f"[AUX] camera frame unavailable: {frame_exc}")
                else:
                    try:
                        image, headers = self.pi.frame(camera_id, view="raw")
                        if not image:
                            raise ValueError("Pi returned an empty camera frame")
                        latest_raw_frame = image
                        observation_received_mono = time.monotonic()
                        observation_received_utc = datetime.now(timezone.utc).isoformat()
                        used_camera = headers.get("X-Automaton-Camera") or camera_id or self.pi.choose_camera()
                    except Exception as e:
                        frame_error = e
                        image = None
                        latest_raw_frame = None
                        print(f"[AUX] camera frame unavailable: {e}")

                if latest_raw_frame is not None and self.detector and self.detector.available():
                    try:
                        detector_started = time.perf_counter()
                        fn = lambda: self.detector.detect_jpeg(latest_raw_frame)
                        objects = self.scheduler.submit(20, fn).result() if self.scheduler else fn()
                        detector_ms = (time.perf_counter() - detector_started) * 1000.0
                    except Exception as e:
                        detector_error = e
                        print(f"[AUX] fast detector unavailable for this frame: {e}")

                if image is not None:
                    vp = self.cfg.get("visual_prompt", "")
                    if objects:
                        vp += "\nFast detector results from the newest sampled frame: " + ", ".join(
                            f"{o['label']} ({o['confidence']:.2f})" for o in objects[:12]
                        )
                    if detector_error is not None:
                        vp += (
                            "\nThe camera frame is available, but the optional fast object detector "
                            "failed for this frame. Analyze the supplied image directly. Do not tell "
                            "the user that the camera feed is unavailable, and do not invent or expose "
                            "a technical failure reason unless the user explicitly asks for diagnostics."
                        )
                    if vp:
                        prompt_parts.append(vp)
                elif frame_error is not None:
                    prompt_parts.append(
                        "The user asked a visual question, but no current camera frame was available. "
                        "Be transparent that you cannot inspect a new image right now. Do not invent "
                        "a technical cause, device error, or CUDA problem unless that cause is explicitly "
                        "provided in user-visible system state."
                    )
            finally:
                vision_ms = (time.perf_counter() - vision_started) * 1000.0

        # Every visual answer has an explicit provenance state. A single-frame
        # fallback is *not* evidence of movement, and an unavailable camera is
        # *not* permission for the language model to infer the current scene.
        if not visual:
            grounding_status = "NOT_REQUESTED"
        elif image is None:
            grounding_status = "UNAVAILABLE"
        elif action_decision.temporal_vision and temporal_samples < 2:
            grounding_status = "STATIC_ONLY"
        elif action_decision.temporal_vision:
            grounding_status = "CURRENT_SEQUENCE"
        else:
            grounding_status = "CURRENT_IMAGE"
        observation_age_ms = (
            max(0, round((time.monotonic() - observation_received_mono) * 1000))
            if observation_received_mono is not None else None
        )
        visual_grounding = {
            "status": grounding_status,
            "camera_id": used_camera if image is not None else None,
            "received_at_utc": observation_received_utc,
            "age_ms_at_prompt": observation_age_ms,
            "frame_count": temporal_samples if temporal_samples else (1 if image is not None else 0),
        }
        if visual:
            prompt_parts.append(
                "[Authoritative visual grounding]\n"
                f"status={grounding_status}; camera={visual_grounding['camera_id'] or 'none'}; "
                f"frames={visual_grounding['frame_count']}; "
                f"received_at_utc={observation_received_utc or 'none'}; "
                f"age_ms_at_prompt={observation_age_ms if observation_age_ms is not None else 'unknown'}. "
                "CURRENT_IMAGE means only a static frame was supplied. CURRENT_SEQUENCE "
                "means multiple ordered frames were supplied. STATIC_ONLY means temporal "
                "capture failed and one static fallback frame was supplied; it cannot "
                "establish a motion trajectory. UNAVAILABLE means no camera imagery was "
                "supplied. Never substitute remembered or imagined visual evidence."
            )

        # Semantic behavior requests cross a narrow Aux -> Pi contract.  This is
        # deliberately separate from CAN/PWM/joint control.  During R&D the Pi
        # broker is planning-only, so submitting an intent tests the complete
        # contract without moving hardware or implying that motion occurred.
        if action_decision.behavior_intent and visual and grounding_status in {"UNAVAILABLE", "STATIC_ONLY"}:
            behavior_result = {
                "status": "rejected_no_observation",
                "executed": False,
                "detail": "Required current visual evidence was not available",
            }
        elif action_decision.behavior_intent:
            try:
                behavior_result = self.pi.submit_behavior(
                    action_decision.behavior_intent,
                    action_decision.behavior_parameters,
                    ttl_ms=int(self.cfg.get("behavior_request_ttl_ms", 5000)),
                )
            except Exception as exc:
                behavior_result = {
                    "status": "unavailable",
                    "executed": False,
                    "detail": str(exc),
                }
                print(f"[AUX] behavior request unavailable: {exc}")

            status = str((behavior_result or {}).get("status", "unknown"))
            executed = bool((behavior_result or {}).get("executed", False))
            prompt_parts.append(
                "[Robot behavior request]\n"
                f"Requested semantic behavior: {action_decision.behavior_intent}. "
                f"Parameters: {action_decision.behavior_parameters}. "
                f"Pi behavior status: {status}; executed={str(executed).lower()}. "
                "This is a high-level request only; you do not control joints, servos, PWM, CAN, "
                "arming, or safety. Never claim that the robot moved merely because the request was "
                "submitted. Claim physical completion only when the Pi explicitly reports a verified "
                "completed/executed result. If status is planning_only or unavailable, explain that "
                "the motion was planned/requested but not physically executed."
            )

        if self.world is not None:
            world_context = self.world.context(text)
            if world_context:
                prompt_parts.append(world_context)

        extra = "\n\n".join(x for x in prompt_parts if x)
        self.state.update(
            "actions",
            last_actions=action_decision.actions,
            visual_reason=action_decision.visual_reason,
            automatic_vision=bool(action_decision.use_vision and not force_vision and not force_temporal_vision),
            temporal_vision=bool(action_decision.temporal_vision),
            visual_grounding=visual_grounding,
            behavior_intent=action_decision.behavior_intent,
            behavior_status=(behavior_result or {}).get("status") if isinstance(behavior_result, dict) else None,
        )
        self.state.update(
            "conversation",
            state="thinking" if decision.mode == "deep" else "answering",
            language=language,
            reasoning_mode=decision.mode,
            reasoning_reason=decision.reason,
            reasoning_score=decision.score,
        )

        verification_used = False

        def generate_reply() -> str:
            nonlocal verification_used
            if grounding_status in {"UNAVAILABLE", "STATIC_ONLY"}:
                if grounding_status == "STATIC_ONLY":
                    fallback = (
                        "I could get one camera image, but not the sequence needed to "
                        "reliably identify your movement. Please try that again."
                    )
                else:
                    fallback = (
                        "I couldn't obtain a current camera image, so I can't "
                        "verify what you're showing me right now. Please try again."
                    )
                if on_reply_delta is not None:
                    on_reply_delta(fallback)
                return fallback
            base_messages = self._messages(text)

            # All deep-reasoning turns are deliberately buffered. Once TALUS
            # starts streaming speech we cannot "un-say" a false start, so the
            # hidden-thinking profile must finish before any final-answer text is
            # presented. Progress cues provide conversational feedback meanwhile.
            # Quantitative engineering turns additionally receive a second private
            # verification pass for formulas, mapping, units and arithmetic.
            if decision.mode == "deep":
                draft = clean_visible_answer(self.llm.chat(
                    base_messages,
                    image_jpeg=image,
                    extra_prompt=extra or None,
                    reasoning_mode="deep",
                ))
                if not draft:
                    raise RuntimeError("The deep-reasoning pass returned an empty final answer.")
                final_reply = draft
                if decision.verification_required:
                    final_reply = clean_visible_answer(self.llm.chat(
                        self._verification_messages(base_messages, draft),
                        image_jpeg=image,
                        extra_prompt=extra or None,
                        reasoning_mode="deep",
                    ))
                    if not final_reply:
                        raise RuntimeError("The quantitative verification pass returned an empty final answer.")
                    verification_used = True
                # Emit only the completed final answer. Passing it as one delta is
                # intentional: SpeechChunker immediately divides it into natural
                # buffered phrases for TTS, but hidden reasoning/drafts cannot leak.
                if on_reply_delta is not None:
                    on_reply_delta(final_reply)
                return final_reply

            # Multimodal responses are buffered before display/TTS. A small
            # number of llama.cpp/Qwen VLM responses have emitted an orphan
            # </think> marker with a draft before it and the polished final
            # answer after it. Buffering lets us remove hidden reasoning and
            # prevents duplicated/marker text from being spoken. Ordinary fast
            # text turns still stream token-by-token below.
            if image is not None:
                final_reply = clean_visible_answer(self.llm.chat(
                    base_messages,
                    image_jpeg=image,
                    extra_prompt=extra or None,
                    reasoning_mode=decision.mode,
                ))
                if not final_reply:
                    raise RuntimeError("The multimodal model returned an empty final answer after output cleanup.")
                if on_reply_delta is not None:
                    on_reply_delta(final_reply)
                return final_reply

            # Fast turns keep low-latency token streaming so TTS can synthesize
            # sentence 1 while Qwen is still generating sentence 2.
            if on_reply_delta is not None and hasattr(self.llm, "stream_chat"):
                parts: list[str] = []
                for chunk in self.llm.stream_chat(
                    base_messages,
                    image_jpeg=image,
                    extra_prompt=extra or None,
                    reasoning_mode=decision.mode,
                ):
                    if not chunk:
                        continue
                    parts.append(str(chunk))
                    on_reply_delta(str(chunk))
                reply_text = "".join(parts).strip()
                if not reply_text:
                    raise RuntimeError("The model stream ended without a final answer.")
                return reply_text
            return clean_visible_answer(self.llm.chat(
                base_messages,
                image_jpeg=image,
                extra_prompt=extra or None,
                reasoning_mode=decision.mode,
            ))

        reply = self._run_with_progress(generate_reply, decision.mode, on_reasoning_wait)

        with self._history_lock:
            context_discarded = turn_epoch != self._reset_epoch
            if not context_discarded:
                self.history.append({"role": "user", "content": text})
                self.history.append({"role": "assistant", "content": reply})
            history_messages = len(self.history)

        if not context_discarded and self.person_session is not None:
            try:
                self.person_session.note_turn_complete(onboarding_result, reply)
            except Exception:
                pass

        # Keep one intentionally lossy rolling topic note for a recognized person.
        # This survives normal conversation resets, but is overwritten each
        # successful turn and is not a transcript or an explicit memory slot.
        last_topic_memory = None
        if not context_discarded and self.person_session is not None:
            try:
                last_topic_memory = self.person_session.note_last_topic(text, reply)
            except Exception:
                last_topic_memory = None

        reply_language_hint = requested_reply_language or language
        reply_language = reply_language_hint
        if self.tts is not None and hasattr(self.tts, "resolve_language"):
            try:
                reply_language = self.tts.resolve_language(reply, hint=reply_language_hint) or reply_language_hint
            except Exception:
                reply_language = reply_language_hint

        elapsed = (time.perf_counter() - started) * 1000
        llm_metrics = {}
        if hasattr(self.llm, "end_turn_metrics"):
            try:
                llm_metrics = self.llm.end_turn_metrics() or {}
            except Exception:
                llm_metrics = {}
        source_ids = list(dict.fromkeys(h.source_id for h in knowledge_hits))
        self.state.update(
            "conversation",
            state="idle",
            language=reply_language,
            input_language=language,
            last_user_text=text,
            last_reply_text=reply,
            last_turn_ms=round(elapsed, 1),
            reasoning_mode=decision.mode,
            reasoning_reason=decision.reason,
            reasoning_score=decision.score,
            verification_used=verification_used,
            history_messages=history_messages,
            llm_ttft_ms=llm_metrics.get("ttft_ms"),
            llm_tokens_per_second=llm_metrics.get("tokens_per_second"),
            llm_completion_tokens=llm_metrics.get("completion_tokens"),
            llm_finish_reason=llm_metrics.get("finish_reason"),
        )
        self.state.update("vision", last_camera=used_camera, last_objects=objects, last_description=reply if visual else None)
        self.state.update(
            "knowledge",
            last_query=text,
            last_sources=source_ids,
            hits=len(knowledge_hits),
            attempted=bool(knowledge_diag.get("attempted")),
            intents=list(knowledge_diag.get("intents") or []),
            retrieval_ms=round(knowledge_ms, 2),
        )
        telemetry_row = {
            "turn_ms": round(elapsed, 2),
            "input_language": language,
            "requested_output_language": requested_reply_language,
            "output_language": reply_language,
            "reasoning_mode": decision.mode,
            "reasoning_reason": decision.reason,
            "verification_used": verification_used,
            "visual_used": bool(image),
            "visual_grounding": visual_grounding,
            "temporal_observation": grounding_status == "CURRENT_SEQUENCE",
            "temporal_samples": temporal_samples,
            "temporal_duration_ms": temporal_duration_ms,
            "vision_ms": round(vision_ms, 2) if vision_ms is not None else None,
            "detector_ms": round(detector_ms, 2) if detector_ms is not None else None,
            "rag_attempted": bool(knowledge_diag.get("attempted")),
            "rag_hits": len(knowledge_hits),
            "rag_sources": source_ids,
            "rag_intents": list(knowledge_diag.get("intents") or []),
            "rag_ms": round(knowledge_ms, 2),
            "actions": list(action_decision.actions),
            "behavior_intent": action_decision.behavior_intent,
            "behavior_status": (behavior_result or {}).get("status") if isinstance(behavior_result, dict) else None,
            "behavior_executed": bool((behavior_result or {}).get("executed", False)) if isinstance(behavior_result, dict) else False,
            "recognized_person": (current_person or {}).get("name") if isinstance(current_person, dict) else None,
            "context_discarded": context_discarded,
            "llm": llm_metrics,
        }
        if self.telemetry is not None:
            try:
                self.telemetry.record_turn(telemetry_row)
                self.state.update("telemetry", **self.telemetry.snapshot())
            except Exception:
                pass
        return {
            "reply": reply,
            "language": reply_language,
            "input_language": language,
            "visual_used": bool(image),
            "visual_grounding": visual_grounding,
            "temporal_observation": grounding_status == "CURRENT_SEQUENCE",
            "temporal_samples": temporal_samples,
            "temporal_duration_ms": temporal_duration_ms,
            "camera_id": used_camera,
            "objects": objects,
            "latency_ms": elapsed,
            "reasoning_mode": decision.mode,
            "reasoning_reason": decision.reason,
            "reasoning_score": decision.score,
            "verification_used": verification_used,
            "knowledge_sources": [h.public_dict() for h in knowledge_hits],
            "knowledge_diagnostics": knowledge_diag,
            "llm_metrics": llm_metrics,
            "person": current_person,
            "personal_memory": personal_memory_result,
            "last_topic_memory": last_topic_memory,
            "context_discarded": context_discarded,
            "actions": action_decision.actions,
            "automatic_vision": bool(action_decision.use_vision and not force_vision and not force_temporal_vision),
            "behavior_intent": action_decision.behavior_intent,
            "behavior_result": behavior_result,
            "visual_reason": action_decision.visual_reason,
            "onboarding": onboarding_result,
        }
