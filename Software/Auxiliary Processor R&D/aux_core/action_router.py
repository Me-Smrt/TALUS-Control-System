from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .util import language_family


@dataclass(frozen=True)
class ActionDecision:
    """Deterministic pre-LLM perception/behavior decision."""

    use_vision: bool = False
    visual_reason: str | None = None
    temporal_vision: bool = False
    behavior_intent: str | None = None
    behavior_parameters: dict[str, Any] = field(default_factory=dict)
    requires_deep: bool = False

    @property
    def actions(self) -> list[str]:
        out: list[str] = []
        if self.temporal_vision:
            out.append("vision_observe")
        elif self.use_vision:
            out.append("vision")
        if self.behavior_intent:
            out.append(f"behavior:{self.behavior_intent}")
        return out


class InteractionActionRouter:
    _DIRECT_VISUAL_RE = re.compile(
        r"\b(?:"
        r"what\s+(?:do|can)\s+you\s+see|"
        r"what(?:'s|\s+is)\s+(?:this|that|here|in\s+front\s+of\s+you)|"
        r"what\s+am\s+i\s+(?:holding|wearing|showing)|"
        r"what\s+(?:object|thing)\s+(?:am\s+i\s+holding|is\s+this|is\s+that)|"
        r"what\s+(?:number|digit)\s+am\s+i\s+(?:showing|holding)(?:\s+up)?|"
        r"which\s+hand\s+am\s+i\s+using|"
        r"where\s+am\s+i\s+pointing|"
        r"what\s+do\s+i\s+have\s+in\s+my\s+hand|"
        # Phrasing such as 'Can you tell me what this number is that I'm
        # showing on my hand in binary?' requires a frame even though it
        # contains none of the shorter camera-trigger phrases above.
        r"(?:what|which|can\s+you\s+tell|tell\s+me)\b.{0,140}\b"
        r"(?:i(?:'m|\s+am)\s+(?:showing|holding|pointing)|on\s+my\s+(?:hand|fingers))|"
        r"what\s+colou?r\s+(?:is|are)|"
        r"can\s+you\s+(?:see|look\s+at|read|recognize|identify)|"
        r"(?:look|take\s+a\s+look)\s+at\s+(?:this|that|me)|"
        r"describe\s+(?:what\s+you\s+see|the\s+(?:room|scene|image|view)|my\s+surroundings)|"
        r"who\s+(?:is|are)\s+(?:here|there|in\s+front\s+of\s+you)|"
        r"how\s+many\s+(?:fingers|people|objects|items)\b|"
        r"read\s+(?:this|that|the\s+sign|the\s+label|the\s+text)|"
        r"what\s+does\s+(?:this|that|the\s+sign|the\s+label)\s+say|"
        r"what(?:'s|\s+is)\s+(?:behind|beside|next\s+to|on)\s+(?:me|you|this|that)"
        r")\b",
        re.IGNORECASE,
    )
    _TEMPORAL_VISUAL_RE = re.compile(
        r"\b(?:"
        r"what\s+(?:does\s+it\s+look\s+like\s+)?(?:i(?:'m|\s+am)|am\s+i)\s+doing|"
        r"what\s+does\s+it\s+look\s+like\s+i(?:'m|\s+am)\s+doing|"
        r"what\s+movement\s+am\s+i\s+doing|"
        r"how\s+am\s+i\s+moving|"
        r"am\s+i\s+(?:dancing|waving|nodding|moving|spinning)|"
        r"can\s+you\s+tell\s+what\s+i(?:'m|\s+am)\s+doing|"
        r"watch\s+me\s+(?:move|dance|wave|do\s+this)"
        r")\b",
        re.IGNORECASE,
    )
    _MIRROR_RE = re.compile(r"\b(?:mirror\s+me|copy\s+my\s+(?:pose|movements?)|mimic\s+me|do\s+what\s+i(?:'m|\s+am)\s+doing)\b", re.IGNORECASE)
    _POINT_RE = re.compile(r"\b(?:please\s+)?point\s+(?:at|to|toward|towards)\s+(?:the\s+)?(?P<target>[^?.!,]{1,120})", re.IGNORECASE)
    _HEAD_LOOK_RE = re.compile(r"\b(?:turn\s+your\s+head|face)\s+(?:to|toward|towards)\s+(?:the\s+)?(?P<target>[^?.!,]{1,120})", re.IGNORECASE)
    _WAVE_RE = re.compile(r"\b(?:wave(?:\s+at\s+(?P<target>[^?.!,]{1,80}))?|give\s+(?:me|them|him|her)\s+a\s+wave)\b", re.IGNORECASE)
    _EXPRESS_RE = re.compile(r"\b(?:express|act|look)\s+(?P<emotion>happy|sad|surprised|confused|excited|curious)\b", re.IGNORECASE)
    _DEICTIC_RE = re.compile(r"\b(?:this|that|these|those|here|there)\b", re.IGNORECASE)
    _VISUAL_VERB_RE = re.compile(
        r"\b(?:see|look|read|show|holding|wearing|colour|color|object|image|camera|scene|sign|label)\b",
        re.IGNORECASE,
    )
    _CURRENT_WORLD_RE = re.compile(
        r"\b(?:in\s+front\s+of\s+you|around\s+you|around\s+me|in\s+the\s+room|right\s+now|currently\s+visible)\b",
        re.IGNORECASE,
    )

    def __init__(self, cfg: dict[str, Any] | None = None):
        self.cfg = dict(cfg or {})
        self.enabled = bool(self.cfg.get("enabled", True))
        self.auto_vision = bool(self.cfg.get("auto_vision", True))

    @staticmethod
    def _target(match: re.Match[str] | None, group: str = "target") -> str | None:
        if match is None:
            return None
        try:
            value = (match.group(group) or "").strip()
        except (IndexError, KeyError):
            return None
        return value.rstrip(" .!?") or None

    def route(
        self,
        text: str,
        *,
        language: str | None = None,
        force_vision: bool = False,
        force_temporal_vision: bool = False,
        visual_keywords: dict[str, list[str]] | None = None,
    ) -> ActionDecision:
        value = str(text or "").strip()

        if force_temporal_vision:
            # A temporal observation is a perception request, not inherently a
            # hard reasoning problem. Keep it on the low-latency multimodal path
            # unless the user explicitly selects /think or a semantic behavior
            # requires planning.
            return ActionDecision(True, "forced_temporal", True, requires_deep=False)
        if force_vision:
            return ActionDecision(True, "forced")
        if not self.enabled:
            return ActionDecision(False, None)

        # Explicit robot behaviors are semantic requests. Spatial behaviors get
        # a fresh image; mirror-pose also gets a temporal observation. The Pi
        # still decides whether/how a validated behavior can become motion.
        match = self._POINT_RE.search(value)
        if match:
            target = self._target(match) or "visible target"
            return ActionDecision(True, "behavior_target", False, "point_at", {"target": target, "arm": "auto", "verification": "visual_depth"}, True)
        match = self._HEAD_LOOK_RE.search(value)
        if match:
            target = self._target(match) or "visible target"
            return ActionDecision(True, "behavior_target", False, "look_at", {"target": target, "verification": "visual_depth"}, True)
        if self._MIRROR_RE.search(value):
            return ActionDecision(True, "behavior_mirror_pose", True, "mirror_pose", {"duration_s": 2.0}, True)
        match = self._WAVE_RE.search(value)
        if match:
            target = self._target(match)
            params = {"name": "wave"}
            if target:
                params["target"] = target
            return ActionDecision(False, "behavior_gesture", False, "gesture", params, True)
        match = self._EXPRESS_RE.search(value)
        if match:
            return ActionDecision(False, "behavior_expression", False, "express", {"emotion": match.group("emotion").casefold(), "intensity": 0.6}, True)

        if not self.auto_vision:
            return ActionDecision(False, None)

        if self._TEMPORAL_VISUAL_RE.search(value):
            # Motion questions need multiple frames, but forcing Qwen's deep
            # thinking profile here made a modest visual question extremely slow
            # on CPU R&D machines. /think still overrides this when desired.
            return ActionDecision(True, "temporal_motion_question", True, requires_deep=False)

        low = value.casefold()
        family = language_family(language)
        keyword_map = visual_keywords or {}
        candidates = list(keyword_map.get(family, [])) + list(keyword_map.get("en", []))
        for keyword in candidates:
            if keyword and str(keyword).casefold() in low:
                return ActionDecision(True, f"configured_keyword:{keyword}")

        if self._DIRECT_VISUAL_RE.search(value):
            return ActionDecision(True, "visual_question")
        if self._CURRENT_WORLD_RE.search(value):
            return ActionDecision(True, "current_scene_reference")
        if self._DEICTIC_RE.search(value) and self._VISUAL_VERB_RE.search(value):
            return ActionDecision(True, "deictic_visual_reference")
        return ActionDecision(False, None)
