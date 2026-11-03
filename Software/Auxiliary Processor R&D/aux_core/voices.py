from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from .util import language_family


class VoiceRegistry:
    """Configured voices plus higher-level voice-set selection.

    Individual voice selection remains available as a debug/backward-compatible
    path. Normal TALUS speech can instead use an active voice set (for example
    ``female`` or ``male``), which chooses an appropriate voice independently
    for each detected language.
    """

    def __init__(
        self,
        path: Path,
        runtime_path: Path,
        default_voice_id: str,
        default_voice_set_id: str | None = None,
    ):
        self.path = path
        self.runtime_path = runtime_path
        self.default = default_voice_id
        self._lock = threading.RLock()
        self._data = json.loads(path.read_text(encoding="utf-8"))
        self._voices = {v["id"]: v for v in self._data.get("voices", [])}
        self._sets = {s["id"]: s for s in self._data.get("voice_sets", [])}
        configured_default_set = str(
            default_voice_set_id or self._data.get("default_voice_set_id", "")
        ).strip()
        self.default_set = configured_default_set if configured_default_set in self._sets else None
        self.active_id, self.active_set_id = self._load_runtime()

    def _load_runtime(self) -> tuple[str | None, str | None]:
        voice_id = None
        set_id = None
        try:
            obj = json.loads(self.runtime_path.read_text(encoding="utf-8"))
            candidate_voice = str(obj.get("active_voice_id", "")).strip()
            candidate_set = str(obj.get("active_voice_set_id", "")).strip()
            if candidate_voice in self._voices:
                voice_id = candidate_voice
            if candidate_set in self._sets:
                set_id = candidate_set
        except Exception:
            pass

        if voice_id is None:
            voice_id = self.default if self.default in self._voices else next(iter(self._voices), None)
        if set_id is None:
            set_id = self.default_set
        return voice_id, set_id

    def _persist(self) -> None:
        self.runtime_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"active_voice_id": self.active_id}
        if self.active_set_id:
            payload["active_voice_set_id"] = self.active_set_id
        self.runtime_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def set_active(self, voice_id: str) -> None:
        """Select one explicit voice and leave voice-set mode.

        This preserves the historical/debug API. Dashboard normal operation now
        selects a voice set instead.
        """
        if voice_id not in self._voices:
            raise KeyError(voice_id)
        if not self._voices[voice_id].get("enabled", True):
            raise ValueError("voice_disabled")
        with self._lock:
            self.active_id = voice_id
            self.active_set_id = None
            self._persist()

    def set_active_set(self, voice_set_id: str) -> None:
        if voice_set_id not in self._sets:
            raise KeyError(voice_set_id)
        if not self._sets[voice_set_id].get("enabled", True):
            raise ValueError("voice_set_disabled")
        with self._lock:
            self.active_set_id = voice_set_id
            # Keep active_id meaningful for old status consumers by mirroring the
            # set's English/default voice when one is explicitly configured.
            voice_set = self._sets[voice_set_id]
            mapped = dict(voice_set.get("language_voices", {})).get("en")
            if mapped in self._voices and self._voices[mapped].get("enabled", True):
                self.active_id = mapped
            self._persist()

    def all(self) -> list[dict[str, Any]]:
        return [dict(v) for v in self._voices.values() if v.get("enabled", True)]

    def all_sets(self) -> list[dict[str, Any]]:
        return [dict(v) for v in self._sets.values() if v.get("enabled", True)]

    def get(self, voice_id: str | None = None) -> dict[str, Any]:
        vid = voice_id or self.active_id
        if not vid or vid not in self._voices:
            raise KeyError(vid)
        return dict(self._voices[vid])

    def get_set(self, voice_set_id: str | None = None) -> dict[str, Any] | None:
        sid = voice_set_id if voice_set_id is not None else self.active_set_id
        if not sid:
            return None
        if sid not in self._sets:
            raise KeyError(sid)
        return dict(self._sets[sid])

    def voice_set_fallback_policy(self, voice_set_id: str | None = None) -> str:
        """Return how a set behaves when it has no voice for a language.

        ``strict`` means TALUS must never leave the selected set.  This is the
        policy used by identity-style sets such as Male/Female and future fun
        character sets.  ``correct_language`` preserves the older mixed-mode
        behavior and is intentionally used by Best available.
        """
        voice_set = self.get_set(voice_set_id)
        if not voice_set:
            return "correct_language"
        policy = str(voice_set.get("fallback_policy", "correct_language")).strip().lower()
        return policy if policy in {"strict", "correct_language"} else "correct_language"

    @staticmethod
    def _voice_languages(voice: dict[str, Any]) -> list[str]:
        return [language_family(x) for x in voice.get("languages", [])]

    def set_candidates_for_language(
        self, voice_set_id: str | None, language: str | None
    ) -> list[dict[str, Any]]:
        """Configured voices that are an exact match for a set and language."""
        voice_set = self.get_set(voice_set_id)
        if not voice_set:
            return []
        fam = language_family(language)
        result: list[dict[str, Any]] = []
        seen: set[str] = set()

        def add(voice_id: str | None) -> None:
            if not voice_id or voice_id in seen:
                return
            voice = self._voices.get(voice_id)
            if not voice or not voice.get("enabled", True):
                return
            langs = self._voice_languages(voice)
            if fam != "und" and "*" not in voice.get("languages", []) and fam not in langs:
                return
            seen.add(voice_id)
            result.append(dict(voice))

        mapped = dict(voice_set.get("language_voices", {})).get(fam)
        add(mapped)

        selector = dict(voice_set.get("selector", {}))
        gender = str(selector.get("gender", "")).strip().lower()
        tags = {str(x).strip().lower() for x in selector.get("tags", []) if str(x).strip()}
        for voice in self.all():
            langs = self._voice_languages(voice)
            if fam != "und" and "*" not in voice.get("languages", []) and fam not in langs:
                continue
            if gender and str(voice.get("gender", "")).strip().lower() != gender:
                continue
            voice_tags = {str(x).strip().lower() for x in voice.get("tags", [])}
            if tags and not tags.issubset(voice_tags):
                continue
            add(str(voice.get("id", "")))
        return result

    def candidates_for_language(
        self,
        language: str | None,
        preferred_id: str | None = None,
        voice_set_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Ordered voice candidates, preserving language over voice-set style."""
        fam = language_family(language)
        result: list[dict[str, Any]] = []
        seen: set[str] = set()

        def add_voice(voice: dict[str, Any] | None) -> None:
            if not voice:
                return
            vid = str(voice.get("id", ""))
            if not vid or vid in seen or not voice.get("enabled", True):
                return
            seen.add(vid)
            result.append(dict(voice))

        # An explicit voice ID is intentionally a hard preview/debug preference.
        if preferred_id is not None:
            add_voice(self.get(preferred_id))
            return result

        sid = voice_set_id if voice_set_id is not None else self.active_set_id
        for voice in self.set_candidates_for_language(sid, fam):
            add_voice(voice)

        # Identity-style voice sets are hard constraints.  If a selected set has
        # no matching voice for this language, do not silently cross into another
        # gender/character set.  The caller may skip speech for this span or the
        # operator may choose Best available (mixed).
        if sid and self.voice_set_fallback_policy(sid) == "strict":
            return result

        fallback_id = dict(self._data.get("fallback_language_voice", {})).get(fam)
        if fallback_id in self._voices:
            add_voice(self._voices[fallback_id])

        # Correct-language fallback is more important than preserving set gender.
        for voice in self.all():
            langs = self._voice_languages(voice)
            if fam == "und" or fam in langs or "*" in voice.get("languages", []):
                add_voice(voice)

        if self.active_id in self._voices:
            add_voice(self._voices[self.active_id])
        return result

    def choose_for_language(
        self,
        language: str | None,
        preferred_id: str | None = None,
        voice_set_id: str | None = None,
    ) -> dict[str, Any]:
        candidates = self.candidates_for_language(language, preferred_id, voice_set_id)
        if candidates:
            return candidates[0]
        return self.get(preferred_id)
