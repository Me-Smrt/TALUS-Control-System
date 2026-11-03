from __future__ import annotations

import copy
import threading
import time
from datetime import datetime, timezone
from typing import Any


DEFAULT_CONTROL_NODES = (
    ("ccb_supervisor", "CCB Supervisor", "CCB"),
    ("head", "Head RCB", "HEAD"),
    ("left_arm", "Left Arm RCB", "LEFT_ARM"),
    ("right_arm", "Right Arm RCB", "RIGHT_ARM"),
    ("torso", "Torso RCB", "TORSO"),
    ("left_hand", "Left Hand RCB", "LEFT_HAND"),
    ("right_hand", "Right Hand RCB", "RIGHT_HAND"),
    ("left_leg", "Left Leg RCB", "LEFT_LEG"),
    ("right_leg", "Right Leg RCB", "RIGHT_LEG"),
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _compact_robot_motion(robot_frame: dict[str, Any]) -> dict[str, Any]:
    robot = robot_frame.get("robot", {}) if isinstance(robot_frame, dict) else {}
    sim = robot_frame.get("simulation", {}) if isinstance(robot_frame, dict) else {}
    face = robot.get("face", {})
    torso = robot.get("torso", {})
    arms = robot.get("arms", {})
    hands = robot.get("hands", {})
    return {
        "timestamp_s": float(robot_frame.get("timestamp_s", 0.0)) if isinstance(robot_frame, dict) else 0.0,
        "torso_valid": bool(torso.get("valid")),
        "face_valid": bool(face.get("valid")),
        "head_rad": copy.deepcopy(face.get("head", {})) if face.get("valid") else {},
        "torso_rad": {
            "yaw": float(torso.get("yaw_rad", 0.0)),
            "side_lean": float(torso.get("bend_rad", 0.0)),
            "tracked_sagittal_lean": float(torso.get("tracked_sagittal_lean_rad", 0.0)),
        } if torso.get("valid") else {},
        "arms": {
            side: {
                "valid": bool(data.get("valid")),
                "converged": bool(data.get("converged", False)),
                "hit_limit": bool(data.get("hit_limit", False)),
                "wrist_error_mm": float(data.get("wrist_error_mm", 0.0)) if data.get("valid") else None,
            }
            for side, data in arms.items()
        },
        "hands": {
            side: {
                "valid": bool(data.get("valid")),
                "wrist_valid": bool(data.get("wrist", {}).get("valid", False)),
            }
            for side, data in hands.items()
        },
        "simulation_profile_active": bool(sim),
        "collision": copy.deepcopy(robot_frame.get("collision", {})),
        "simulation_collision": copy.deepcopy(sim.get("collision", {})),
        "simulation_gesture": copy.deepcopy(robot_frame.get("simulation_gesture", {})),
    }


class RobotStateHub:
    """Single in-process snapshot of what the Pi currently knows.

    This is descriptive state, not a safety authority.  Hardware safety remains
    owned by the CCB/RCBs and the dedicated Pi hardware-control process.  Until
    that process is connected, safety/node fields are deliberately marked
    unverified rather than guessed.
    """

    schema = "automaton.pi_state.v1"

    def __init__(self, *, version: str = "0.3.0", planned_auxiliary: str = "Jetson Orin Nano") -> None:
        self._lock = threading.RLock()
        self._perception_condition = threading.Condition(self._lock)
        self._sequence = 0
        self._started_monotonic_ns = time.monotonic_ns()
        self._latest_perception_detail: dict[str, Any] = {}
        self._state: dict[str, Any] = {
            "schema": self.schema,
            "service_version": version,
            "generated_at_utc": utc_now_iso(),
            "generated_monotonic_ns": time.monotonic_ns(),
            "sequence": 0,
            "system": {
                "status": "starting",
                "mode": "R&D",
                "uptime_s": 0.0,
                "health": {},
            },
            "safety": {
                "verified": False,
                "armed": False,
                "estop": "unknown",
                "global_servo_allow": False,
                "mode": "R&D_DISARMED",
                "source": "awaiting_hardware_control_integration",
            },
            "control_nodes": {
                node_id: {
                    "id": node_id,
                    "label": label,
                    "role": role,
                    "status": "unavailable",
                    "healthy": None,
                    "armed": False,
                    "faults": [],
                    "last_seen_monotonic_ns": None,
                    "channel": None,
                    "interface": None,
                    "uid": None,
                }
                for node_id, label, role in DEFAULT_CONTROL_NODES
            },
            "perception": {
                "status": "starting",
                "tracking_camera_id": None,
                "fps": 0.0,
                "face": False,
                "body": False,
                "hands": {"left": False, "right": False},
                "last_frame_monotonic_ns": None,
                "last_frame_unix_ns": None,
                "age_ms": None,
            },
            "motion": {
                "status": "idle",
                "authoritative_targets": True,
                "simulation_profile": "servo_velocity_acceleration_limited",
                "summary": {},
            },
            "cameras": {},
            "audio": {
                "input": {"status": "unprobed", "label": "USB microphone (planned)"},
                "output": {"status": "unprobed", "label": "USB speaker (planned)"},
            },
            "auxiliary": {
                "planned_type": planned_auxiliary,
                "status": "not_connected",
                "connected": False,
                "last_seen_monotonic_ns": None,
                "latency_ms": None,
            },
        }

    def _touch(self) -> None:
        self._sequence += 1
        self._state["sequence"] = self._sequence
        self._state["generated_at_utc"] = utc_now_iso()
        self._state["generated_monotonic_ns"] = time.monotonic_ns()
        self._state["system"]["uptime_s"] = (
            self._state["generated_monotonic_ns"] - self._started_monotonic_ns
        ) / 1_000_000_000.0

    def set_system_status(self, status: str) -> None:
        with self._lock:
            self._state["system"]["status"] = str(status)
            self._touch()

    def update_health(self, health: dict[str, Any]) -> None:
        with self._lock:
            self._state["system"]["health"] = copy.deepcopy(health)
            self._touch()

    def update_camera(self, camera_id: str, **values: Any) -> None:
        with self._lock:
            current = self._state["cameras"].setdefault(str(camera_id), {"id": str(camera_id)})
            current.update(copy.deepcopy(values))
            self._touch()

    def update_audio(self, audio: dict[str, Any]) -> None:
        with self._lock:
            self._state["audio"] = copy.deepcopy(audio)
            self._touch()

    def update_perception(self, perception: dict[str, Any], robot_frame: dict[str, Any], *, fps: float,
                          camera_id: str, monotonic_ns: int, unix_ns: int, frame_sequence: int | None = None) -> None:
        face = perception.get("face", {})
        body = perception.get("body", {})
        hands = perception.get("hands", {})
        with self._lock:
            self._latest_perception_detail = {
                "schema": "automaton.perception.v1",
                "camera_id": camera_id,
                "frame_sequence": int(frame_sequence) if frame_sequence is not None else None,
                "captured_monotonic_ns": int(monotonic_ns),
                "captured_unix_ns": int(unix_ns),
                "perception": copy.deepcopy(perception),
            }
            self._state["perception"] = {
                "status": "tracking",
                "tracking_camera_id": camera_id,
                "fps": float(fps),
                "face": bool(face.get("valid")),
                "body": bool(body.get("valid")),
                "hands": {
                    "left": bool(hands.get("left", {}).get("valid")),
                    "right": bool(hands.get("right", {}).get("valid")),
                },
                "head_pose_rad": copy.deepcopy(face.get("head_pose_rad", {})),
                "eyelids_closed": copy.deepcopy(face.get("eyelids_closed", {})),
                "gaze": copy.deepcopy(face.get("gaze", {})),
                "last_frame_monotonic_ns": int(monotonic_ns),
                "last_frame_unix_ns": int(unix_ns),
                "age_ms": 0.0,
            }
            self._state["motion"]["status"] = "tracking"
            self._state["motion"]["summary"] = _compact_robot_motion(robot_frame)
            self._touch()
            self._perception_condition.notify_all()

    def mark_perception_stopped(self, reason: str = "stopped") -> None:
        with self._lock:
            self._state["perception"]["status"] = str(reason)
            self._state["motion"]["status"] = "idle"
            self._touch()

    def update_control_node(self, node_id: str, **values: Any) -> None:
        with self._lock:
            current = self._state["control_nodes"].setdefault(str(node_id), {"id": str(node_id)})
            current.update(copy.deepcopy(values))
            self._touch()

    def update_safety(self, **values: Any) -> None:
        with self._lock:
            self._state["safety"].update(copy.deepcopy(values))
            self._touch()

    def update_auxiliary(self, **values: Any) -> None:
        with self._lock:
            self._state["auxiliary"].update(copy.deepcopy(values))
            self._touch()


    def wait_for_perception_at_or_after(self, captured_monotonic_ns: int, *, timeout_s: float = 0.2) -> dict[str, Any]:
        """Return the perception snapshot aligned to, or newer than, a sampled frame."""
        deadline = time.monotonic() + max(0.0, float(timeout_s))
        target = int(captured_monotonic_ns)
        with self._perception_condition:
            while True:
                current = copy.deepcopy(self._latest_perception_detail)
                try:
                    captured = int(current.get("captured_monotonic_ns", -1))
                except (TypeError, ValueError):
                    captured = -1
                if current and captured >= target:
                    return current
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return current
                self._perception_condition.wait(remaining)

    def perception_detail(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._latest_perception_detail)

    def world_snapshot(self) -> dict[str, Any]:
        """Derived read-only pose state; the present tracker handles one primary subject.

        Additional anonymous people and objects are tracked by AUX YOLO.
        """
        snap = self.snapshot()
        data = snap.get('perception', {})
        age = data.get('age_ms')
        current = data.get('status') == 'tracking' and age is not None and age <= 2500
        primary = []
        if current and (data.get('face') or data.get('body')):
            primary.append({'id': 'primary_pose', 'source': 'mediapipe_primary_subject',
                            'body': data.get('body'), 'face': data.get('face'),
                            'hands': data.get('hands', {}), 'age_ms': round(age)})
        return {'schema': 'talus.pi_world.v1', 'status': 'current' if current else 'stale_or_unavailable',
                'source': 'pi_mediapipe', 'camera_id': data.get('tracking_camera_id'),
                'age_ms': age, 'primary_subjects': primary,
                'multi_person_pose_supported': False,
                'robot_motion': snap.get('motion', {}).get('summary', {}),
                'safety': {'verified': False, 'description': 'perception is not hardware safety authorization'}}

    def snapshot(self) -> dict[str, Any]:
        now = time.monotonic_ns()
        with self._lock:
            out = copy.deepcopy(self._state)
        last = out.get("perception", {}).get("last_frame_monotonic_ns")
        if last is not None:
            out["perception"]["age_ms"] = max(0.0, (now - int(last)) / 1_000_000.0)
        for node in out.get("control_nodes", {}).values():
            seen = node.get("last_seen_monotonic_ns")
            node["age_ms"] = None if seen is None else max(0.0, (now - int(seen)) / 1_000_000.0)
        return out
