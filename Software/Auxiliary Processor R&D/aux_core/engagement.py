from __future__ import annotations

import math
import re
import time
from typing import Any


_WORD = re.compile(r"[^\W_]+(?:['’][^\W_]+)?", re.UNICODE)


class EngagementManager:
    """Decide whether an utterance is directed at TALUS.

    Wake-name recognition intentionally operates on a small deterministic alias
    list after STT rather than rewriting the transcript globally.  This lets
    phrases such as "Hey Talos" address TALUS while preserving literal uses of
    the word elsewhere (for example, "tell me about Talos from mythology").
    """

    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg
        self.engaged_until = 0.0

    @staticmethod
    def _tokens(text: str) -> list[str]:
        return [m.group(0).casefold() for m in _WORD.finditer(str(text or ""))]

    def _wake_name_match(self, text: str) -> dict[str, Any] | None:
        tokens = self._tokens(text)
        if not tokens:
            return None

        canonical = str(self.cfg.get("wake_name", "TALUS") or "TALUS").strip()
        aliases = {
            str(v).strip().casefold()
            for v in self.cfg.get("wake_name_aliases", [])
            if str(v).strip()
        }
        if canonical:
            aliases.add(canonical.casefold())
        if not aliases:
            return None

        prefixes = {
            str(v).strip().casefold()
            for v in self.cfg.get("wake_name_prefixes", ["hey", "okay", "ok"])
            if str(v).strip()
        }

        # Strongest case: an explicit direct-address prefix immediately followed
        # by the canonical name or an observed STT alias.
        if len(tokens) >= 2 and tokens[0] in prefixes and tokens[1] in aliases:
            return {
                "matched": True,
                "kind": "wake_name_prefixed",
                "raw_alias": tokens[1],
                "canonical": canonical or "TALUS",
            }

        # Also allow a bare name at the start of the utterance, which supports
        # natural speech such as "TALUS, can you see me?".  We intentionally do
        # not match aliases in the middle of a sentence so "tell me about Talos"
        # remains ordinary content rather than a wake event.
        if bool(self.cfg.get("allow_bare_wake_name", True)) and tokens[0] in aliases:
            return {
                "matched": True,
                "kind": "wake_name_bare",
                "raw_alias": tokens[0],
                "canonical": canonical or "TALUS",
            }
        return None

    def wake_match(self, text: str) -> dict[str, Any] | None:
        tokens = self._tokens(text)
        for phrase in self.cfg.get("wake_phrases", []):
            p = str(phrase or "").strip()
            phrase_tokens = self._tokens(p)
            if not phrase_tokens:
                continue
            width = len(phrase_tokens)
            if any(tokens[i : i + width] == phrase_tokens for i in range(max(0, len(tokens) - width + 1))):
                return {
                    "matched": True,
                    "kind": "wake_phrase",
                    "raw_alias": p,
                    "canonical": p,
                }
        return self._wake_name_match(text)

    def _wake(self, text: str):
        return self.wake_match(text) is not None

    @staticmethod
    def _num(v, default=99.0):
        try:
            return float(v)
        except Exception:
            return default

    def evaluate(self, text: str, pi_state: dict[str, Any] | None, now: float | None = None) -> dict[str, Any]:
        now = time.monotonic() if now is None else now
        if not self.cfg.get("enabled", True):
            return {"accept": True, "score": 1.0, "reason": "disabled", "engaged": True}
        if now < self.engaged_until:
            self.engaged_until = now + float(self.cfg.get("active_window_s", 25))
            return {"accept": True, "score": 1.0, "reason": "active_conversation", "engaged": True}

        score = 0.0
        reasons = []
        wake = self.wake_match(text)
        if wake:
            score += float(self.cfg.get("wake_score", 1))
            reasons.append("wake_phrase")

        p = (pi_state or {}).get("perception", {})
        if p.get("face"):
            score += float(self.cfg.get("face_score", .18))
            reasons.append("face_visible")
            hp = p.get("head_pose_rad", {}) or {}
            yaw = abs(math.degrees(self._num(hp.get("yaw"), 99)))
            pitch = abs(math.degrees(self._num(hp.get("pitch"), 99)))
            if yaw <= float(self.cfg.get("head_yaw_limit_deg", 28)) and pitch <= float(self.cfg.get("head_pitch_limit_deg", 24)):
                score += float(self.cfg.get("head_attention_score", .28))
                reasons.append("head_toward_robot")
            gaze = p.get("gaze", {}) or {}
            vals = []

            def collect(x):
                if isinstance(x, dict):
                    for k, v in x.items():
                        if k in {"pan", "tilt", "x", "y"}:
                            try:
                                vals.append(abs(float(v)))
                            except Exception:
                                pass
                        else:
                            collect(v)
                elif isinstance(x, (list, tuple)):
                    for v in x:
                        collect(v)
                elif isinstance(x, (int, float)):
                    vals.append(abs(float(x)))

            collect(gaze)
            if vals and max(vals) <= max(float(self.cfg.get("gaze_pan_limit", .35)), float(self.cfg.get("gaze_tilt_limit", .35))):
                score += float(self.cfg.get("gaze_attention_score", .36))
                reasons.append("gaze_toward_robot")

        # Direct eye contact is useful evidence, but it is intentionally not
        # mandatory.  A visible face with the head oriented toward TALUS is a
        # natural direct-address cue on its own.  This also makes engagement
        # robust to sunglasses, gaze-estimation noise, and people looking at an
        # object while continuing to speak to the robot.
        face_head_direct = (
            "face_visible" in reasons
            and "head_toward_robot" in reasons
            and bool(self.cfg.get("head_attention_direct_address", True))
        )
        score_accept = score >= float(self.cfg.get("idle_accept_score", .72))
        accept = bool(wake) or face_head_direct or score_accept
        if accept:
            self.touch(now)

        result = {
            "accept": accept,
            "score": round(score, 3),
            "reason": "+".join(reasons) or "insufficient_direct_address",
            "engaged": accept,
            "accept_basis": (
                "wake" if wake else
                "face_head_direct_address" if face_head_direct else
                "score_threshold" if score_accept else
                "rejected"
            ),
        }
        if wake:
            result["wake"] = wake
        return result

    def touch(self, now: float | None = None) -> float:
        """Renew the active-conversation window from *now*.

        The live audio loop calls this after TALUS finishes its reply so time
        spent on STT, LLM inference, and TTS playback does not consume the
        user's follow-up window.  Returns the new monotonic deadline.
        """
        now = time.monotonic() if now is None else float(now)
        self.engaged_until = now + float(self.cfg.get("active_window_s", 25))
        return self.engaged_until

    def reset(self):
        self.engaged_until = 0.0
