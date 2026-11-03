from __future__ import annotations

import copy
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from .contracts import BehaviorIntent
from .motion_interface import MotionController, validate_behavior_intent


@dataclass
class BehaviorRecord:
    request_id: str
    intent: str
    parameters: dict[str, Any]
    priority: int
    received_monotonic_ns: int
    expires_monotonic_ns: int
    status: str
    executed: bool = False
    detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        now = time.monotonic_ns()
        return {
            "request_id": self.request_id,
            "intent": self.intent,
            "parameters": copy.deepcopy(self.parameters),
            "priority": self.priority,
            "received_monotonic_ns": self.received_monotonic_ns,
            "expires_monotonic_ns": self.expires_monotonic_ns,
            "expired": now >= self.expires_monotonic_ns,
            "status": self.status,
            "executed": bool(self.executed),
            "detail": self.detail,
        }


class BehaviorBroker:
    """High-level Aux -> Pi behavior boundary.

    This object never translates intents into PWM/CAN/servo writes.  It validates
    semantic requests and, only when a deterministic MotionController backend is
    explicitly attached, hands the validated intent to that backend.

    The default R&D configuration is planning-only.  That lets the complete
    network/action contract be exercised before robot hardware exists without
    creating a path that can accidentally actuate the robot.
    """

    def __init__(
        self,
        *,
        controller: MotionController | None = None,
        planning_only: bool = True,
        default_ttl_ms: int = 5000,
        max_ttl_ms: int = 15000,
        max_records: int = 128,
    ) -> None:
        self.controller = controller
        self.planning_only = bool(planning_only)
        self.default_ttl_ms = max(250, int(default_ttl_ms))
        self.max_ttl_ms = max(self.default_ttl_ms, int(max_ttl_ms))
        self.max_records = max(8, int(max_records))
        self._lock = threading.RLock()
        self._records: OrderedDict[str, BehaviorRecord] = OrderedDict()

    def _ttl_ms(self, payload: dict[str, Any]) -> int:
        # issued/expires monotonic values come from the Aux host. Absolute
        # monotonic timestamps are NOT comparable across machines, but their
        # difference is, so derive a duration and start a fresh Pi-local TTL.
        ttl = payload.get("ttl_ms")
        if ttl is None:
            try:
                issued = int(payload.get("issued_monotonic_ns"))
                expires = int(payload.get("expires_monotonic_ns"))
                delta = expires - issued
                if delta > 0:
                    ttl = round(delta / 1_000_000)
            except (TypeError, ValueError):
                ttl = None
        try:
            value = int(ttl) if ttl is not None else self.default_ttl_ms
        except (TypeError, ValueError):
            value = self.default_ttl_ms
        return max(250, min(self.max_ttl_ms, value))

    def submit(self, payload: dict[str, Any]) -> dict[str, Any]:
        validate_behavior_intent(payload)
        request_id = str(payload.get("request_id", "")).strip()
        if not request_id or len(request_id) > 128:
            raise ValueError("request_id is required and must be <= 128 characters")

        with self._lock:
            existing = self._records.get(request_id)
            if existing is not None:
                return existing.as_dict()

        now = time.monotonic_ns()
        ttl_ms = self._ttl_ms(payload)
        intent = BehaviorIntent(
            intent=str(payload.get("intent", "")),
            request_id=request_id,
            issued_monotonic_ns=now,
            expires_monotonic_ns=now + ttl_ms * 1_000_000,
            parameters=copy.deepcopy(payload.get("parameters", {})),
            priority=int(payload.get("priority", 0)),
        )

        record = BehaviorRecord(
            request_id=request_id,
            intent=intent.intent,
            parameters=copy.deepcopy(intent.parameters),
            priority=intent.priority,
            received_monotonic_ns=now,
            expires_monotonic_ns=intent.expires_monotonic_ns,
            status="planning_only",
            executed=False,
            detail="No deterministic motion backend is attached; intent was validated but not executed.",
        )

        if not self.planning_only and self.controller is not None:
            status = str(self.controller.submit_intent(intent))
            record.status = status
            record.executed = status.casefold() in {"complete", "completed", "executed", "success"}
            record.detail = None
        elif not self.planning_only and self.controller is None:
            record.status = "motion_backend_unavailable"
            record.detail = "Motion execution is enabled by configuration, but no controller backend is attached."

        with self._lock:
            self._records[request_id] = record
            self._records.move_to_end(request_id)
            while len(self._records) > self.max_records:
                self._records.popitem(last=False)
        return record.as_dict()

    def get(self, request_id: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._records.get(str(request_id))
            return None if record is None else record.as_dict()

    def cancel(self, request_id: str) -> dict[str, Any] | None:
        request_id = str(request_id)
        with self._lock:
            record = self._records.get(request_id)
            if record is None:
                return None

        cancelled = False
        if self.controller is not None and not self.planning_only:
            try:
                cancelled = bool(self.controller.cancel_intent(request_id))
            except Exception:
                cancelled = False

        with self._lock:
            record = self._records.get(request_id)
            if record is None:
                return None
            record.status = "cancelled" if (self.planning_only or cancelled) else "cancel_failed"
            record.executed = False
            record.detail = None if record.status == "cancelled" else "Motion backend did not confirm cancellation."
            return record.as_dict()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            records = list(self._records.values())
        return {
            "schema": "automaton.behavior_broker.v1",
            "planning_only": self.planning_only,
            "motion_backend_attached": self.controller is not None,
            "motion_backend": "blender_simulation_only" if (self.controller is not None and
                self.controller.__class__.__name__ == "BlenderGestureController") else
                ("none" if self.controller is None else "other"),
            "records": [r.as_dict() for r in records[-16:]],
        }
