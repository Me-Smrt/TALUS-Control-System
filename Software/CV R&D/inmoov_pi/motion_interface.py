from __future__ import annotations

from typing import Any, Protocol

from .contracts import ALLOWED_AUXILIARY_INTENT_CLASSES, FORBIDDEN_DIRECT_CONTROL_FIELDS, BehaviorIntent


class IntentValidationError(ValueError):
    pass


class MotionController(Protocol):
    """Boundary a deterministic hardware motion layer must implement.

    The auxiliary node talks only in BehaviorIntent objects. A concrete Pi
    controller resolves them into legal robot targets and enforces current
    robot/safety state before anything can reach RCBs.
    """

    def submit_intent(self, intent: BehaviorIntent) -> str:
        ...

    def cancel_intent(self, request_id: str) -> bool:
        ...


def validate_behavior_intent(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise IntentValidationError("behavior intent payload must be an object")
    intent = str(payload.get("intent", ""))
    if intent not in ALLOWED_AUXILIARY_INTENT_CLASSES:
        raise IntentValidationError(f"unsupported high-level intent: {intent!r}")
    params = payload.get("parameters", {})
    if not isinstance(params, dict):
        raise IntentValidationError("parameters must be an object")

    def walk(obj: Any, path: str = "") -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                key_l = str(key).casefold()
                if key_l in FORBIDDEN_DIRECT_CONTROL_FIELDS:
                    raise IntentValidationError(f"direct-control field is forbidden at {path + str(key)}")
                walk(value, path + str(key) + ".")
        elif isinstance(obj, (list, tuple)):
            for i, value in enumerate(obj):
                walk(value, path + f"{i}.")

    walk(params, "parameters.")

    # Constrain the first behavior family now, before a hardware executor exists.
    # These fields express goals, never joint-level mechanics.
    if intent in {"point_at", "look_at", "attention_target"}:
        target = str(params.get("target", params.get("target_id", ""))).strip()
        if not target or len(target) > 200:
            raise IntentValidationError(f"{intent} requires a short semantic target")
        arm = str(params.get("arm", "auto")).casefold()
        if arm not in {"auto", "left", "right"}:
            raise IntentValidationError("arm must be auto, left, or right")
        verification = str(params.get("verification", "visual")).casefold()
        if verification not in {"none", "visual", "depth", "visual_depth"}:
            raise IntentValidationError("verification must be none, visual, depth, or visual_depth")

    if intent == "express":
        emotion = str(params.get("emotion", "")).strip()
        if not emotion or len(emotion) > 64:
            raise IntentValidationError("express requires an emotion/preset name")
        if "intensity" in params:
            try:
                intensity = float(params["intensity"])
            except (TypeError, ValueError) as exc:
                raise IntentValidationError("intensity must be numeric") from exc
            if not 0.0 <= intensity <= 1.0:
                raise IntentValidationError("intensity must be between 0 and 1")

    if intent in {"gesture", "pose"}:
        name = str(params.get("name", "")).strip()
        if not name or len(name) > 80:
            raise IntentValidationError(f"{intent} requires a curated preset name")

    if intent == "mirror_pose":
        if "duration_s" in params:
            try:
                duration = float(params["duration_s"])
            except (TypeError, ValueError) as exc:
                raise IntentValidationError("duration_s must be numeric") from exc
            if not 0.25 <= duration <= 10.0:
                raise IntentValidationError("mirror_pose duration_s must be between 0.25 and 10")
