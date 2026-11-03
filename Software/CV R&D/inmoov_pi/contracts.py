from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


API_SCHEMA = "automaton.pi_api.v1"
STATE_SCHEMA = "automaton.pi_state.v1"
PERCEPTION_SCHEMA = "automaton.perception.v1"
AUXILIARY_INTENT_SCHEMA = "automaton.aux_intent.v1"


@dataclass(frozen=True)
class MessageStamp:
    sequence: int
    monotonic_ns: int
    unix_ns: int
    source: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "sequence": int(self.sequence),
            "monotonic_ns": int(self.monotonic_ns),
            "unix_ns": int(self.unix_ns),
            "source": self.source,
        }


@dataclass(frozen=True)
class BehaviorIntent:
    """Future auxiliary -> Pi high-level request.

    Intents deliberately describe *what* the robot should try to do, not PWM,
    CAN frames, or raw joint writes.  The Pi motion/safety layers remain the
    authority that decides whether and how an intent becomes motion.
    """

    intent: str
    request_id: str
    issued_monotonic_ns: int
    expires_monotonic_ns: int
    parameters: dict[str, Any] = field(default_factory=dict)
    priority: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": AUXILIARY_INTENT_SCHEMA,
            "intent": self.intent,
            "request_id": self.request_id,
            "issued_monotonic_ns": self.issued_monotonic_ns,
            "expires_monotonic_ns": self.expires_monotonic_ns,
            "parameters": self.parameters,
            "priority": self.priority,
        }


ALLOWED_AUXILIARY_INTENT_CLASSES = (
    "look_at",
    "speak",
    "gesture",
    "pose",
    "attention_target",
    "request_scene_analysis",
    "point_at",
    "express",
    "mirror_pose",
    "stop_behavior",
)

FORBIDDEN_DIRECT_CONTROL_FIELDS = (
    "pwm",
    "pulse_us",
    "can_id",
    "servo_channel",
    "local_servo_enable",
    "global_servo_allow",
    "arm_hardware",
    "joint_angle",
    "joint_angles",
    "joint_name",
    "joint_names",
    "position_permille",
    "raw_trajectory",
)
