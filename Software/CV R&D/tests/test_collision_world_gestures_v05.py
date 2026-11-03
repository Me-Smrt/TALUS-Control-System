from __future__ import annotations

import time
import numpy as np

from inmoov_cv.collision import InterArmGuard, segment_distance
from inmoov_cv.kinematics import ArmChain
from inmoov_cv.util import load_json
from inmoov_pi.contracts import BehaviorIntent
from inmoov_pi.sim_gestures import BlenderGestureController
from inmoov_pi.state import RobotStateHub


def setup_guard():
    kin=load_json('config/inmoov_kinematics.json')
    arms={side:ArmChain(kin['arms'][side]) for side in ('left','right')}
    return kin, arms, InterArmGuard(arms,kin)


def test_segment_distance_and_collision_blocking():
    assert abs(segment_distance([0,0,0],[1,0,0],[.5,-1,0],[.5,1,0])) < 1e-6
    kin,arms,guard=setup_guard()
    neutral={s:arm.neutral for s,arm in arms.items()}
    assert guard.path(neutral,neutral)['blocked'] is False
    collide={'left':np.array([.30624548,1.86952821,-.46522614,1.29874694]),
             'right':np.array([1.30002658,1.90411969,-.10009275,1.31925807])}
    assert guard.check(collide['left'],collide['right'])['blocked'] is True
    assert guard.path(neutral,collide)['blocked'] is True


def test_simulation_gestures_are_named_and_hardware_never_claimed():
    kin,_,_=setup_guard()
    controller=BlenderGestureController(kin)
    issued=time.monotonic_ns()
    make=lambda name: BehaviorIntent('gesture','request',issued,issued+10_000_000_000,{'name':name})
    assert controller.submit_intent(make('wave')) == 'simulation_queued'
    frame={'robot':{'arms':{'left':{'valid':False},'right':{'valid':False}}}}
    out=controller.apply(frame)
    assert out['simulation_gesture']['hardware_executed'] is False
    assert out['robot']['arms']['right']['valid'] is True
    assert controller.cancel_intent('request') is True
    assert controller.submit_intent(make('nonexistent')) == 'simulation_unsupported'
    assert controller.submit_intent(make('nod')) == 'simulation_queued'
    out=controller.apply({'robot':{'face':{'valid':False}}})
    assert out['robot']['face']['valid'] is True


def test_pi_world_reports_only_current_primary_pose():
    state=RobotStateHub()
    assert state.world_snapshot()['primary_subjects']==[]
    snap=state.world_snapshot()
    assert snap['multi_person_pose_supported'] is False
    assert snap['safety']['verified'] is False


def test_pi_world_api_endpoint():
    import json
    import urllib.request
    from inmoov_pi.api_server import ControlApiServer
    from inmoov_pi.frame_store import LatestFrameStore
    api=ControlApiServer({'bind_host':'127.0.0.1','port':0,'allow_unauthenticated_loopback':True},
                         RobotStateHub(),LatestFrameStore())
    api.start()
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{api.port}/v1/world',timeout=3) as response:
            world=json.load(response)
        assert world['schema']=='talus.pi_world.v1'
        assert world['primary_subjects']==[]
    finally:
        api.stop()
