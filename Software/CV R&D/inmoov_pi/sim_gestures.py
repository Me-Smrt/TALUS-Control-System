from __future__ import annotations

"""Named simulation-only gestures injected into the existing Blender frame stream.

This controller never owns actuator hardware or receives raw joint targets from AUX.
Unsupported semantic intents remain planning-only/rejected for this backend.
"""

import copy
import math
import threading
import time
from typing import Any

import numpy as np

from inmoov_cv.collision import InterArmGuard
from inmoov_cv.kinematics import ArmChain
from .contracts import BehaviorIntent


class BlenderGestureController:
    def __init__(self, kin: dict[str, Any], collision_cfg: dict[str, Any] | None = None):
        self.arms = {s: ArmChain(kin['arms'][s]) for s in ('left', 'right')}
        self.guard = InterArmGuard(self.arms, kin, collision_cfg)
        self._lock = threading.RLock()
        self._active: dict[str, Any] | None = None
        self._last_rejection: str | None = None
        self._safe = {s: self.arms[s].neutral.copy() for s in self.arms}

    def submit_intent(self, intent: BehaviorIntent) -> str:
        if intent.intent == 'stop_behavior':
            with self._lock:
                self._active = None
            return 'simulation_cancelled'
        if intent.intent != 'gesture':
            return 'simulation_unsupported'
        name = str(intent.parameters.get('name', '')).casefold().strip()
        if name not in {'wave', 'nod', 'shake_head'}:
            return 'simulation_unsupported'
        with self._lock:
            self._active = {'id': intent.request_id, 'name': name, 'started': time.monotonic(),
                            'expires': intent.expires_monotonic_ns}
        return 'simulation_queued'

    def cancel_intent(self, request_id: str) -> bool:
        with self._lock:
            if self._active and self._active['id'] == request_id:
                self._active = None
                return True
        return False

    def apply(self, frame: dict[str, Any]) -> dict[str, Any]:
        """Modify this frame before the speed-limited simulation adapter.

        Preserve the live perception tree but replace only the named simulated
        joints. The collision guard checks a path between previous safe states.
        """
        with self._lock:
            active = copy.copy(self._active) if self._active else None
        if not active:
            return frame
        elapsed = time.monotonic()-active['started']
        if elapsed >= 2.8 or time.monotonic_ns() >= active['expires']:
            with self._lock:
                if self._active and self._active['id'] == active['id']:
                    self._active = None
            return frame
        phase = min(1., elapsed/2.8)
        envelope = min(1., phase*6., (1.-phase)*6.)
        robot = frame.setdefault('robot', {})
        name = active['name']
        if name in {'nod', 'shake_head'}:
            face = robot.setdefault('face', {})
            face['valid'] = True
            head = face.setdefault('head', {})
            key = 'nod_rad' if name == 'nod' else 'turn_rad'
            head[key] = float(0.19 * envelope * math.sin(elapsed*2.*math.pi*1.0))
        elif name == 'wave':
            arm_commands = robot.setdefault('arms', {})
            q = {side: self.arms[side].neutral.copy() for side in ('left','right')}
            # Curated absolute preset bounded by the model's own joint limits.
            # Wave the RIGHT arm; never accept a raw joint number from AUX.
            desired = np.array([1.14, 0.15, 0.18, 1.12], dtype=float)
            q['right'] = self.arms['right'].neutral + envelope * (desired - self.arms['right'].neutral)
            q['right'][2] += envelope*0.23*math.sin(elapsed*2.*math.pi*1.3)
            for side in q:
                q[side] = np.clip(q[side], self.arms[side].lower, self.arms[side].upper)
            result = self.guard.path(self._safe, q, steps=16)
            if result['blocked']:
                self._last_rejection = result['reason']
                with self._lock:
                    self._active = None
                frame['simulation_gesture'] = {'status': 'blocked_collision', 'name': name,
                                               'collision': result}
                return frame
            self._safe = {side: item.copy() for side, item in q.items()}
            for side in ('left','right'):
                cmd = arm_commands.setdefault(side, {})
                cmd.update({'valid': True, 'joint_names': [j['name'] for j in self.arms[side].joints],
                            'joint_angles_rad': q[side].tolist()})
        frame['simulation_gesture'] = {'status': 'simulation_only', 'name': name,
                                      'request_id': active['id'], 'hardware_executed': False}
        return frame
