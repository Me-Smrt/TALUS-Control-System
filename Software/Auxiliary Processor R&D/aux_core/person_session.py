from __future__ import annotations

import re
import threading
import time
from typing import Any

import numpy as np


_REMEMBER_RE = re.compile(
    r"^\s*(?:please\s+)?remember(?:\s+this)?(?:\s*[:,-]\s*|\s+that\s+)(.+?)\s*$",
    re.IGNORECASE,
)
_NAME_RE = re.compile(
    r"^\s*(?:my\s+name\s+is|you\s+can\s+call\s+me|call\s+me|i['’]?m|i\s+am)\s+(.+?)\s*[.!]?\s*$",
    re.IGNORECASE,
)
_REMEMBER_ME_AS_RE = re.compile(
    r"^\s*(?:please\s+)?remember\s+me\s+(?:as|by\s+the\s+name)\s+(.+?)\s*[.!]?\s*$",
    re.IGNORECASE,
)
_YES_RE = re.compile(r"^\s*(?:yes|yeah|yep|sure|okay|ok|please do|do that|remember me|you can remember me)[.!]?\s*$", re.IGNORECASE)
_NO_RE = re.compile(r"^\s*(?:no|nope|not now|don't|do not|session only|just for now)[.!]?\s*$", re.IGNORECASE)
_AFFIRMATIVE_START_RE = re.compile(
    r"^\s*(?:yes|yeah|yep|sure|okay|ok|absolutely|definitely|sounds good|that sounds good|go ahead|please do|you can|that's fine|that is fine)\b",
    re.IGNORECASE,
)
_NEGATIVE_START_RE = re.compile(
    r"^\s*(?:no|nope|nah|not now|don't|do not|please don't|rather not|session only|just for now)\b",
    re.IGNORECASE,
)

_NAME_STOPWORDS = {
    "fine", "good", "great", "okay", "ok", "here", "ready", "tired", "busy", "working",
    "studying", "doing", "homework", "hungry", "back", "well", "not", "just", "currently",
}




def _consent_reply(text: str) -> bool | None:
    """Interpret a reply only while persistent-identity consent is pending.

    This intentionally accepts conversational answers such as
    "Sure! Sounds good to me. I have homework to do" without treating arbitrary
    later uses of the word "sure" as consent.  It is called only when TALUS has
    just offered local face enrollment.
    """
    value = str(text or "").strip()
    if not value:
        return None
    if _NO_RE.match(value) or _NEGATIVE_START_RE.match(value):
        return False
    if _YES_RE.match(value) or _AFFIRMATIVE_START_RE.match(value):
        return True
    return None

def _clean_name_candidate(value: str) -> str | None:
    value = re.sub(r"\s+", " ", str(value).strip()).strip(" .,!?:;\"")
    if not value or len(value) > 60:
        return None
    words = value.split()
    if not 1 <= len(words) <= 3:
        return None
    if any(w.casefold() in _NAME_STOPWORDS for w in words):
        return None
    if not all(re.fullmatch(r"[A-Za-z][A-Za-z'’\-]*", w) for w in words):
        return None
    return " ".join(w[:1].upper() + w[1:] for w in words)


def _explicit_name(text: str) -> str | None:
    m = _NAME_RE.match(str(text))
    return _clean_name_candidate(m.group(1)) if m else None


def _short_name_reply(text: str) -> str | None:
    # Only used immediately after TALUS has asked the person's name.
    return _clean_name_candidate(str(text))


def _compact_topic(user_text: str, reply_text: str, max_chars: int = 360) -> str:
    """Create a deliberately lossy topic-level memory without another LLM call."""
    def clean(value: str) -> str:
        value = re.sub(r"[`*_>#]+", " ", str(value))
        value = re.sub(r"\s+", " ", value).strip()
        return value

    user = clean(user_text)
    reply = clean(reply_text)
    # The first answer sentence adds enough grounding for follow-ups such as
    # "what offices did you say were there?" without storing the transcript.
    first_answer = re.split(r"(?<=[.!?])\s+", reply, maxsplit=1)[0].strip() if reply else ""
    if first_answer:
        topic = f"User topic: {user} | TALUS response summary: {first_answer}"
    else:
        topic = f"User topic: {user}"
    return topic[: max(80, int(max_chars))].rstrip()


class PersonSessionManager:
    """Bind transient conversation context to the primary visible person.

    Presence comes from the Pi's existing MediaPipe face state.  Persistent
    identity is optional and uses a local embedding backend.  Losing the primary
    face beyond a small grace period clears conversation context even when the
    identity model is unavailable.
    """

    def __init__(self, cfg, pi, store, identity, state, *, conversation=None, engagement=None):
        self.cfg = dict(cfg or {})
        self.pi = pi
        self.store = store
        self.identity = identity
        self.state = state
        self.conversation = conversation
        self.engagement = engagement
        self.enabled = bool(self.cfg.get("enabled", True))
        self.poll_s = max(0.15, float(self.cfg.get("poll_interval_s", 0.5)))
        self.leave_grace_s = max(0.0, float(self.cfg.get("leave_grace_s", 2.5)))
        self.recognition_interval_s = max(0.5, float(self.cfg.get("recognition_interval_s", 2.0)))
        self.touch_interval_s = max(1.0, float(self.cfg.get("touch_interval_s", 30.0)))
        self.match_threshold = float(self.cfg.get("match_threshold", 0.45))
        self.confirmations = max(1, int(self.cfg.get("identity_confirmations", 2)))
        self.unknown_confirmations = max(1, int(self.cfg.get("unknown_confirmations", 2)))
        self.enrollment_samples = max(1, int(self.cfg.get("enrollment_samples", 3)))
        self.enrollment_spacing_s = max(0.0, float(self.cfg.get("enrollment_spacing_s", 0.25)))
        self.onboarding_enabled = bool(self.cfg.get("onboarding_enabled", True))
        self.ask_name_after_turns = max(0, int(self.cfg.get("ask_name_after_turns", 0)))
        self.ask_name_retry_turns = max(1, int(self.cfg.get("ask_name_retry_turns", 2)))
        self.offer_persistent_identity = bool(self.cfg.get("offer_persistent_identity", True))
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._face_present = False
        self._last_face_seen = 0.0
        self._last_recognition = 0.0
        self._last_touch = 0.0
        self._current_id: str | None = None
        self._current_name: str | None = None
        self._current_score: float | None = None
        self._candidate_id: str | None = None
        self._candidate_count = 0
        self._unknown_count = 0
        self._unknown_confirmed = False
        self._unknown_turns = 0
        self._last_name_prompt_turn = -1000
        self._awaiting_name = False
        self._temporary_name: str | None = None
        self._awaiting_remember_consent = False
        self._declined_persistence = False
        self._last_reset_for_absence = False
        self._update_state("startup")

    def attach(self, *, conversation=None, engagement=None) -> None:
        if conversation is not None:
            self.conversation = conversation
        if engagement is not None:
            self.engagement = engagement

    def start(self) -> None:
        if not self.enabled or self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="aux-person-session", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _face_valid(self, payload: dict[str, Any]) -> bool:
        p = payload.get("perception", {}) if isinstance(payload, dict) else {}
        face = p.get("face", {}) if isinstance(p, dict) else {}
        return bool(face.get("valid"))

    def _reset_onboarding_locked(self) -> None:
        self._unknown_confirmed = False
        self._unknown_turns = 0
        self._last_name_prompt_turn = -1000
        self._awaiting_name = False
        self._temporary_name = None
        self._awaiting_remember_consent = False
        self._declined_persistence = False

    def _onboarding_stage_locked(self) -> str:
        if self._current_id is not None:
            return "recognized"
        if self._awaiting_remember_consent:
            return "consent_pending"
        if self._temporary_name:
            return "session_name"
        if self._awaiting_name:
            return "name_pending"
        if self._face_present:
            return "unknown_visible"
        return "no_face"

    def _refresh_presence_for_turn(self) -> None:
        """Best-effort synchronous presence check before a conversational turn."""
        try:
            detail = self.pi.perception()
            present = self._face_valid(detail)
        except Exception:
            return
        now = time.monotonic()
        with self._lock:
            self._face_present = present
            if present:
                self._last_face_seen = now
                self._last_reset_for_absence = False
                if not self.identity.available() and self._current_id is None:
                    self._unknown_confirmed = True

    def _ensure_identity_checked(self) -> None:
        """Check stored faces before deciding that a visible person is unknown."""
        self._refresh_presence_for_turn()
        with self._lock:
            if not self._face_present or self._current_id is not None:
                return
        if not self.identity.available():
            return
        # Do enough immediate checks to satisfy the same confirmation rule used
        # by the background watcher. This prevents TALUS asking a known person
        # their name merely because the polling thread had not run yet.
        for _ in range(self.confirmations):
            self._recognize_once()
            with self._lock:
                if self._current_id is not None:
                    return
        with self._lock:
            if self._current_id is None and self._face_present:
                self._unknown_confirmed = True

    def process_user_text(self, text: str) -> dict[str, Any] | None:
        """Handle natural identity onboarding before Qwen sees the turn.

        Diagnostic slash commands remain available, but normal interaction can
        now discover an unknown person, ask their name, and—with explicit
        consent—enroll their face without requiring /enroll.
        """
        if not self.enabled or not self.onboarding_enabled:
            return None
        self._ensure_identity_checked()
        with self._lock:
            if self._current_id is not None:
                return None
            if not self._face_present:
                return None
            awaiting_name = self._awaiting_name
            awaiting_consent = self._awaiting_remember_consent
            temp_name = self._temporary_name

        raw = str(text).strip()

        # Explicit "remember me as <name>" is itself consent to persist the
        # local face ID, so it may enroll immediately when models are available.
        m = _REMEMBER_ME_AS_RE.match(raw)
        if m:
            name = _clean_name_candidate(m.group(1))
            if name and self.identity.available():
                try:
                    person = self.enroll_current(name, clear_history=False)
                    return {
                        "action": "person_enrolled", "name": person["name"], "saved": True,
                        "prompt_context": (
                            "[Identity action]\nThe visible user explicitly asked to be remembered as "
                            f"{person['name']}. Their local face identity was enrolled successfully. "
                            "Acknowledge this briefly and naturally; do not overuse their name."
                        ),
                    }
                except Exception as exc:
                    return {
                        "action": "enrollment_failed", "name": name, "saved": False,
                        "prompt_context": f"[Identity action]\nThe user asked to be remembered as {name}, but local enrollment failed: {exc}. Do not claim it was saved.",
                    }

        if awaiting_consent and temp_name:
            consent = _consent_reply(raw)
            if consent is True:
                if self.identity.available():
                    try:
                        person = self.enroll_current(temp_name, clear_history=False)
                        return {
                            "action": "person_enrolled", "name": person["name"], "saved": True,
                            "prompt_context": (
                                f"[Identity action]\nThe user consented to being remembered as {person['name']}. "
                                "Their local face identity was saved successfully. Confirm this briefly."
                            ),
                        }
                    except Exception as exc:
                        return {
                            "action": "enrollment_failed", "name": temp_name, "saved": False,
                            "prompt_context": f"[Identity action]\nThe user consented to local recognition, but enrollment failed: {exc}. Do not claim it succeeded.",
                        }
                with self._lock:
                    self._awaiting_remember_consent = False
                return {
                    "action": "identity_unavailable", "name": temp_name, "saved": False,
                    "prompt_context": (
                        f"[Identity action]\nThe user said TALUS may remember them as {temp_name}, but the local face-recognition backend is unavailable. "
                        "Use their name for this visible session only and be honest that persistent recognition was not saved."
                    ),
                }
            if consent is False:
                with self._lock:
                    self._awaiting_remember_consent = False
                    self._declined_persistence = True
                return {
                    "action": "persistence_declined", "name": temp_name, "saved": False,
                    "prompt_context": (
                        f"[Identity onboarding]\nThe user prefers to be called {temp_name} for this session but declined persistent face recognition. "
                        "Respect that choice and do not ask again during this visible session."
                    ),
                }
            # A non-answer should not restart name onboarding or cause TALUS to
            # nag on every later turn.  Keep the temporary session name and
            # leave explicit 'remember me' available if the user decides later.
            with self._lock:
                self._awaiting_remember_consent = False
            return {
                "action": "session_name", "name": temp_name, "saved": False,
                "prompt_context": (
                    f"[Identity status]\nThe visible user asked to be called {temp_name} for this session. "
                    "They did not give a clear answer about persistent face recognition. Keep using the session name naturally, "
                    "do not ask their name again, and do not repeatedly ask about persistence."
                ),
            }

        name = _explicit_name(raw)
        if not name and awaiting_name:
            name = _short_name_reply(raw)
        if name:
            with self._lock:
                self._temporary_name = name
                self._awaiting_name = False
                can_offer = self.offer_persistent_identity and self.identity.available() and not self._declined_persistence
                self._awaiting_remember_consent = bool(can_offer)
            if can_offer:
                return {
                    "action": "session_name_learned", "name": name, "ask_remember": True,
                    "prompt_context": (
                        f"[Identity onboarding]\nThe visible user just told you their name is {name}. Use it naturally. "
                        "This is a newly learned session name, not evidence that they are returning; do not say 'welcome back' unless persistent recognition actually matched them. "
                        "Before ending this reply, briefly ask whether they would like TALUS to remember them for future visits. "
                        "If useful, explain that this stores a local face ID and only a small bounded set of user-approved memories."
                    ),
                }
            return {
                "action": "session_name_learned", "name": name,
                "prompt_context": (f"[Identity onboarding]\nThe visible user told you their name is {name}. Use it naturally for this session. "
                                   "This does not mean they are a returning recognized person; do not imply prior recognition."),
            }

        with self._lock:
            if self._temporary_name:
                return {
                    "action": "session_name",
                    "name": self._temporary_name,
                    "prompt_context": (
                        f"[Identity status]\nThe visible user asked to be called {self._temporary_name} for this session. "
                        "Use that name only where natural. Do not ask their name again and do not imply persistent recognition."
                    ),
                }
            self._unknown_turns += 1
            turn_no = self._unknown_turns
            due = turn_no > self.ask_name_after_turns and (
                not self._awaiting_name or (turn_no - self._last_name_prompt_turn) >= self.ask_name_retry_turns
            )
            if due:
                self._awaiting_name = True
                self._last_name_prompt_turn = turn_no

        if due:
            return {
                "action": "ask_name", "ask_name": True,
                "prompt_context": (
                    "[Identity onboarding]\nA person is visibly present, but TALUS does not recognize them and does not know what to call them. "
                    "Before ending this reply, naturally ask what they would like to be called. If they asked a substantive question, answer it first. "
                    "Do not invent a name and do not claim to remember this person yet."
                ),
            }
        return {
            "action": "unknown_person",
            "prompt_context": "[Identity status]\nA visible person is not currently recognized. Do not assume their identity or name.",
        }

    def note_turn_complete(self, onboarding: dict[str, Any] | None, reply: str) -> None:
        """Keep onboarding retries honest if Qwen ignored a required social step."""
        if not onboarding:
            return
        if onboarding.get("ask_name"):
            asked = bool(re.search(r"\b(?:your name|what should i call you|what can i call you|call you)\b", str(reply), re.IGNORECASE))
            if not asked:
                with self._lock:
                    # Make the next turn immediately eligible for another prompt.
                    self._last_name_prompt_turn -= self.ask_name_retry_turns
        self._update_state(str(onboarding.get("action") or "onboarding_turn"))

    def _update_state(self, event: str | None = None) -> None:
        counts = self.store.counts()
        with self._lock:
            values = {
                "face_present": self._face_present,
                "current_person_id": self._current_id,
                "current_name": self._current_name,
                "match_score": self._current_score,
                "identity_backend_available": bool(self.identity.available()),
                "people_count": counts["people"],
                "memory_count": counts["memories"],
                "unknown_face_confirmed": self._unknown_confirmed,
                "session_name": self._temporary_name,
                "onboarding_stage": self._onboarding_stage_locked(),
            }
            if event is not None:
                values["last_event"] = str(event)
        self.state.update("people", **values)

    def _clear_session(self, reason: str) -> None:
        with self._lock:
            self._current_id = None
            self._current_name = None
            self._current_score = None
            self._candidate_id = None
            self._candidate_count = 0
            self._unknown_count = 0
            self._reset_onboarding_locked()
        if self.conversation is not None:
            self.conversation.clear_history(reason)
        if self.engagement is not None:
            try:
                self.engagement.reset()
            except Exception:
                pass
        self._update_state(reason)

    def _set_match(self, match) -> None:
        with self._lock:
            prior = self._current_id
            if match is None:
                return
            self._unknown_count = 0
            if self._candidate_id == match.person_id:
                self._candidate_count += 1
            else:
                self._candidate_id = match.person_id
                self._candidate_count = 1
            if self._candidate_count < self.confirmations:
                return
            changed = prior is not None and prior != match.person_id
            resolved_from_unknown = prior is None and self.conversation is not None and self.conversation.history_size() > 0
            self._current_id = match.person_id
            self._current_name = match.name
            self._current_score = float(match.score)
            self._candidate_id = None
            self._candidate_count = 0
            self._unknown_confirmed = False
            self._unknown_turns = 0
            self._awaiting_name = False
            self._temporary_name = None
            self._awaiting_remember_consent = False
            self._declined_persistence = False
        now = time.monotonic()
        if self._last_touch == 0.0 or (now - self._last_touch) >= self.touch_interval_s or prior != match.person_id:
            self.store.touch(match.person_id)
            self._last_touch = now
        if changed or resolved_from_unknown:
            if self.conversation is not None:
                self.conversation.clear_history("person_identity_changed")
        self._update_state("person_recognized")

    def _recognize_once(self) -> None:
        if not self.identity.available():
            return
        try:
            jpeg, _headers = self.pi.frame(None, view="raw")
            emb = self.identity.embedding_from_jpeg(jpeg)
            match = self.store.match(emb, self.match_threshold)
            if match is not None:
                self._set_match(match)
            else:
                with self._lock:
                    has_current = self._current_id is not None
                    self._unknown_count += 1
                    misses = self._unknown_count
                    if not has_current and misses >= self.unknown_confirmations:
                        self._unknown_confirmed = True
                if has_current and misses >= self.unknown_confirmations:
                    self._clear_session("person_identity_no_longer_matches")
                elif not has_current and misses >= self.unknown_confirmations:
                    self._update_state("unknown_person_confirmed")
        except Exception:
            # Recognition is auxiliary context, never a reason to kill the main
            # conversation/control process.
            return

    def _tick(self) -> None:
        now = time.monotonic()
        try:
            detail = self.pi.perception()
            present = self._face_valid(detail)
        except Exception:
            # A Pi API outage should not masquerade as "person left"; preserve
            # the session until actual perception resumes.
            return

        with self._lock:
            was_present = self._face_present
            previous_last_seen = self._last_face_seen
            already_cleared = self._last_reset_for_absence
            self._face_present = present
            if present:
                # A momentary missed face frame must not erase a pending name or
                # temporary session identity. The configured departure grace
                # applies to onboarding state as well as conversation history.
                brief_reacquire = bool(
                    not was_present
                    and previous_last_seen
                    and not already_cleared
                    and (now - previous_last_seen) < self.leave_grace_s
                )
                self._last_face_seen = now
                self._last_reset_for_absence = False
            else:
                brief_reacquire = False

        if present:
            if not was_present:
                if not brief_reacquire:
                    with self._lock:
                        # A genuinely new visible session starts anonymous until
                        # recognition resolves. Brief frame dropouts are preserved.
                        if self._current_id is None:
                            self._unknown_turns = 0
                            self._last_name_prompt_turn = -1000
                            self._awaiting_name = False
                            self._temporary_name = None
                            self._awaiting_remember_consent = False
                            self._declined_persistence = False
                            if not self.identity.available():
                                self._unknown_confirmed = True
                self._update_state("face_reacquired" if brief_reacquire else "face_entered")
            if (now - self._last_recognition) >= self.recognition_interval_s:
                self._last_recognition = now
                self._recognize_once()
            return

        if was_present:
            self._update_state("face_temporarily_lost")
        if self._last_reset_for_absence:
            return
        with self._lock:
            last = self._last_face_seen
        if last and (now - last) >= self.leave_grace_s:
            self._last_reset_for_absence = True
            self._clear_session("person_left_frame")

    def _run(self) -> None:
        while not self._stop.wait(self.poll_s):
            self._tick()

    def status(self) -> dict[str, Any]:
        self._update_state(None)
        snap = self.state.snapshot().get("people", {})
        return dict(snap)

    def current_person(self) -> dict[str, Any] | None:
        with self._lock:
            pid = self._current_id
        return self.store.get(pid) if pid else None

    def prompt_context(self) -> str:
        person = self.current_person()
        if not person:
            with self._lock:
                temp_name = self._temporary_name
                face_present = self._face_present
                declined = self._declined_persistence
            if temp_name:
                suffix = " The user declined persistent recognition for this visible session." if declined else " This session name is not yet a persisted face identity."
                return (
                    "[Current-session person context]\n"
                    f"Name provided this session: {temp_name}.{suffix} "
                    "Use the name only where natural and do not imply that persistent recognition exists unless enrollment succeeded."
                )
            if face_present:
                return "[Identity status]\nA person is visible but is not currently matched to a stored identity. Do not invent a name or personal memories."
            return ""
        memories = self.store.memories(person["person_id"])
        lines = [
            "[Recognized person context]",
            f"Name: {person['name']}",
            "Use the person's name only where it sounds natural; do not repeat it constantly.",
        ]
        if memories:
            lines.append("Explicit memories this person asked the robot to retain:")
            lines.extend(f"- {m['text']}" for m in memories)
        topic = self.store.last_topic(person["person_id"])
        # Exact in-memory history wins while a conversation is active. The
        # lossy topic note is only injected after direct context has been reset.
        direct_context_empty = self.conversation is None or self.conversation.history_size() == 0
        if topic and direct_context_empty:
            lines.append("Approximate last-conversation topic (lossy rolling memory, not a transcript):")
            lines.append(f"- {topic['text']}")
            lines.append(
                "If this helps answer a follow-up after context was cleared, be explicit that you only remember the general topic, "
                "not the exact prior exchange. Do not invent missing details."
            )
        return "\n".join(lines)

    def note_last_topic(self, user_text: str, reply_text: str) -> dict[str, Any] | None:
        """Update one rolling topic note for the currently recognized person.

        This memory is intentionally approximate and overwritten every successful
        turn. It is not part of the bounded explicit-memory list.
        """
        if not bool(self.cfg.get("remember_last_topic", True)):
            return None
        person = self.current_person()
        if not person:
            return None
        topic = _compact_topic(
            user_text, reply_text, int(self.cfg.get("max_topic_chars", 360))
        )
        if not topic:
            return None
        saved = self.store.set_last_topic(person["person_id"], topic)
        self._update_state("last_topic_updated")
        return {"name": person["name"], **saved}

    def maybe_remember(self, text: str) -> dict[str, Any] | None:
        m = _REMEMBER_RE.match(str(text))
        if not m:
            return None
        memory = " ".join(m.group(1).strip().split())
        person = self.current_person()
        if not person:
            return {"requested": True, "saved": False, "reason": "no_recognized_person", "text": memory}
        saved = self.store.remember(person["person_id"], memory)
        self._update_state("memory_saved")
        return {"requested": True, "saved": True, "person_id": person["person_id"], "name": person["name"], **saved}

    def remember_current(self, text: str) -> dict[str, Any]:
        person = self.current_person()
        if not person:
            raise RuntimeError("No recognized person is active")
        out = self.store.remember(person["person_id"], text)
        self._update_state("memory_saved")
        return {"name": person["name"], **out}

    def enroll_current(self, name: str, *, clear_history: bool = True) -> dict[str, Any]:
        if not self.identity.available():
            raise RuntimeError("Face identity models are not installed; see docs/PERSON_IDENTITY.md")
        embeddings = []
        for i in range(self.enrollment_samples):
            jpeg, _headers = self.pi.frame(None, view="raw")
            embeddings.append(self.identity.embedding_from_jpeg(jpeg))
            if i + 1 < self.enrollment_samples and self.enrollment_spacing_s:
                time.sleep(self.enrollment_spacing_s)
        mean = np.mean(np.stack(embeddings), axis=0)
        norm = float(np.linalg.norm(mean))
        if norm <= 1e-8:
            raise RuntimeError("Unable to build a valid face enrollment")
        person = self.store.register(name, mean / norm)
        with self._lock:
            self._current_id = person["person_id"]
            self._current_name = person["name"]
            self._current_score = 1.0
            self._last_touch = time.monotonic()
            self._unknown_count = 0
            self._face_present = True
            self._last_face_seen = time.monotonic()
            self._unknown_confirmed = False
            self._unknown_turns = 0
            self._awaiting_name = False
            self._temporary_name = None
            self._awaiting_remember_consent = False
            self._declined_persistence = False
        if clear_history and self.conversation is not None:
            self.conversation.clear_history("person_enrolled")
        self._update_state("person_enrolled")
        return person

    def forget_current(self) -> bool:
        with self._lock:
            pid = self._current_id
        if not pid:
            return False
        removed = self.store.delete(pid)
        self._clear_session("person_forgotten")
        return removed
