from __future__ import annotations

"""Conservative capsule-based INTER-ARM collision preview in torso coordinates.

Not a certified hardware collision checker: this intentionally does not model
finger meshes, tool payloads, torso/head shells, backlash or servo feedback.
"""

import numpy as np
from typing import Any


def segment_distance(a: np.ndarray, b: np.ndarray, c: np.ndarray, d: np.ndarray) -> float:
    """Minimum Euclidean separation of two 3-D line segments (including endpoints)."""
    a,b,c,d = [np.asarray(x, dtype=float) for x in (a,b,c,d)]
    u, v, w = b-a, d-c, a-c
    aa, bb, cc, dd, ee = float(u@u), float(u@v), float(v@v), float(u@w), float(v@w)
    den = aa*cc-bb*bb
    s_n, s_d, t_n, t_d = 0., den, 0., den
    if den < 1e-12:
        s_n, s_d, t_n, t_d = 0., 1., ee, cc
    else:
        s_n = bb*ee-cc*dd
        t_n = aa*ee-bb*dd
        if s_n < 0.: s_n, t_n, t_d = 0., ee, cc
        elif s_n > s_d: s_n, t_n, t_d = s_d, ee+bb, cc
    if t_n < 0.:
        t_n = 0.
        if -dd < 0.: s_n = 0.
        elif -dd > aa: s_n = s_d
        else: s_n, s_d = -dd, aa
    elif t_n > t_d:
        t_n = t_d
        if -dd+bb < 0.: s_n = 0.
        elif -dd+bb > aa: s_n = s_d
        else: s_n, s_d = -dd+bb, aa
    sc = 0. if abs(s_n)<1e-12 else s_n/s_d
    tc = 0. if abs(t_n)<1e-12 else t_n/t_d
    return float(np.linalg.norm(w+sc*u-tc*v))


class InterArmGuard:
    def __init__(self, arms: dict[str, Any], kin: dict[str, Any], config: dict[str, Any] | None = None):
        self.arms = arms
        self.cfg = dict(config or {})
        self.enabled = bool(self.cfg.get('enabled', True))
        self.margin_m = max(0., float(self.cfg.get('margin_mm', 15.))/1000.)
        self.upper_radius = max(0., float(self.cfg.get('upper_arm_radius_mm', 35.))/1000.)
        self.fore_radius = max(0., float(self.cfg.get('forearm_radius_mm', 35.))/1000.)
        self.hand_radius = max(0., float(self.cfg.get('hand_radius_mm', 45.))/1000.)
        self.base = {side: np.asarray(kin['arms'][side]['shoulder_base_origin_torso_m'], dtype=float)
                     for side in ('left','right')}

    def arm_segments(self, side: str, q: np.ndarray) -> list[tuple[np.ndarray,np.ndarray,float,str]]:
        _, elbow, wrist = self.arms[side].forward(q)
        shoulder = self.base[side]
        elbow, wrist = elbow+shoulder, wrist+shoulder
        return [(shoulder, elbow, self.upper_radius, 'upper_arm'),
                (elbow, wrist, self.fore_radius, 'forearm'),
                (wrist, wrist, self.hand_radius, 'hand')]

    def check(self, left: np.ndarray, right: np.ndarray) -> dict[str, Any]:
        if not self.enabled:
            return {'blocked': False, 'min_clearance_mm': None, 'reason': 'disabled'}
        if (not np.all(np.isfinite(left)) or not np.all(np.isfinite(right))):
            return {'blocked': True, 'min_clearance_mm': None, 'reason': 'invalid_joint_values'}
        min_clearance = float('inf')
        pair = None
        for a,b,ra,name_a in self.arm_segments('left', left):
            for c,d,rb,name_b in self.arm_segments('right', right):
                clearance = segment_distance(a,b,c,d) - ra - rb
                if clearance < min_clearance:
                    min_clearance, pair = clearance, f'left_{name_a}:right_{name_b}'
        return {'blocked': min_clearance < self.margin_m,
                'min_clearance_mm': round(min_clearance*1000., 2),
                'reason': 'inter_arm_capsule_clearance' if min_clearance < self.margin_m else 'clear',
                'closest_pair': pair, 'approximate_geometry': True}

    def path(self, start: dict[str, np.ndarray], target: dict[str,np.ndarray], *, steps: int = 12) -> dict[str, Any]:
        for alpha in np.linspace(0.,1.,max(2,steps)+1)[1:]:
            ql = (1-alpha)*start['left']+alpha*target['left']
            qr = (1-alpha)*start['right']+alpha*target['right']
            status = self.check(ql, qr)
            if status['blocked']:
                return status | {'sample_alpha': round(float(alpha),3)}
        return self.check(target['left'], target['right'])
