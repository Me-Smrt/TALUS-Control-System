"""Camera ambiguity must not advance accepted robot joint commands."""
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from inmoov_cv import retarget as retarget_mod
from inmoov_cv.retarget import RobotRetargeter
from inmoov_cv.util import load_json

ROOT=Path(__file__).resolve().parents[1]

def test_large_ik_jump_is_held_without_advancing_solver(monkeypatch):
    cfg=load_json(ROOT/'config/default.json')
    target=RobotRetargeter(cfg,ROOT/'config/inmoov_kinematics.json')
    monkeypatch.setattr(retarget_mod,'torso_basis',lambda body:(np.eye(3),0.,0.,0.))
    def fake_arm(side,source,body,basis,t):
        return {'valid':True,'joint_angles_rad':(target.last_safe_q[side] + 1.7).tolist(),
                'joint_names':[j['name'] for j in target.arms[side].joints],
                'wrist_error_mm':5.,'elbow_error_mm':5.}
    monkeypatch.setattr(target,'_arm_command',fake_arm)
    face=SimpleNamespace(valid=False)
    body=SimpleNamespace(valid=True, joint_metrics_rad={})
    hands={'left':SimpleNamespace(valid=False),'right':SimpleNamespace(valid=False)}
    result=target.retarget(100.,face,body,hands)
    for side in ('left','right'):
        assert result['robot']['arms'][side]['tracking_rejected']=='joint_jump'
        assert result['robot']['arms'][side]['collision_held']
        np.testing.assert_allclose(result['robot']['arms'][side]['joint_angles_rad'],target.last_safe_q[side])
        np.testing.assert_allclose(target.last_q[side],target.last_safe_q[side])
