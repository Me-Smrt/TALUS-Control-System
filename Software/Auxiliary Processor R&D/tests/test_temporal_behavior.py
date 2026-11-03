import cv2
import numpy as np

from aux_core.action_router import InteractionActionRouter
from aux_core.conversation import ConversationManager


def _jpeg(value=90):
    img = np.full((90, 120, 3), value, dtype=np.uint8)
    ok, enc = cv2.imencode('.jpg', img)
    assert ok
    return enc.tobytes()


class CapturingLlm:
    def __init__(self):
        self.extra = ''
        self.image = None
        self.mode = None

    def chat(self, messages, image_jpeg=None, extra_prompt=None, reasoning_mode=None):
        self.extra = extra_prompt or ''
        self.image = image_jpeg
        self.mode = reasoning_mode
        return 'Observed safely.'


class Pi:
    def __init__(self):
        self.behaviors = []
        self.observe_calls = 0

    def choose_camera(self):
        return 'aurora'

    def frame(self, *args, **kwargs):
        return _jpeg(100), {'X-Automaton-Camera': 'aurora'}

    def observe(self, *args, **kwargs):
        self.observe_calls += 1
        frames = [_jpeg(70), _jpeg(100), _jpeg(130)]
        manifest = {
            'schema': 'automaton.temporal_observation.v1',
            'camera_id': 'aurora',
            'actual_duration_ms': 1000.0,
            'depth': {'available': False},
            'frames': [
                {
                    'file': f'frame_{i:02d}.jpg',
                    'relative_ms': i * 500.0,
                    'perception': {
                        'body': {
                            'keypoints': {
                                'left_wrist': {'image_normalized': [0.25 + i * 0.1, 0.50, 0.0]},
                                'right_wrist': {'image_normalized': [0.75 - i * 0.1, 0.50, 0.0]},
                            }
                        },
                        'face': {'head_pose_rad': {'yaw': i * 0.05}},
                    },
                }
                for i in range(3)
            ],
        }
        return {'manifest': manifest, 'frames': frames, 'headers': {}}

    def submit_behavior(self, intent, parameters=None, **kwargs):
        self.behaviors.append((intent, dict(parameters or {})))
        return {
            'request_id': 'test',
            'intent': intent,
            'parameters': dict(parameters or {}),
            'status': 'planning_only',
            'executed': False,
        }


class Detector:
    def available(self):
        return False


class State:
    def update(self, *args, **kwargs):
        pass


def _conv(llm=None, pi=None):
    return ConversationManager(
        {
            'history_turns': 2,
            'visual_keywords': {'en': []},
            'visual_prompt': 'Use visual evidence only.',
            'action_router': {'enabled': True, 'auto_vision': True},
            'temporal_vision': {'duration_ms': 1000, 'samples': 3, 'max_width': 320},
        },
        llm or CapturingLlm(),
        pi or Pi(),
        Detector(),
        None,
        State(),
    )


def test_temporal_motion_question_requests_observation_without_forcing_deep_reasoning():
    pi = Pi()
    llm = CapturingLlm()
    out = _conv(llm, pi).handle_text("What does it look like I'm doing?", language='en')
    assert pi.observe_calls == 1
    assert out['temporal_observation'] is True
    assert out['temporal_samples'] == 3
    assert out['reasoning_mode'] == 'fast'
    assert llm.mode == 'fast'
    assert isinstance(llm.image, (bytes, bytearray)) and len(llm.image) > 100
    assert 'chronological contact sheet' in llm.extra.lower()
    assert 'deterministic cue, not an activity label' in llm.extra.lower()


def test_point_at_clock_submits_only_semantic_planning_intent():
    pi = Pi()
    llm = CapturingLlm()
    out = _conv(llm, pi).handle_text('Point at the clock.', language='en')
    assert out['behavior_intent'] == 'point_at'
    assert pi.behaviors == [('point_at', {'target': 'clock', 'arm': 'auto', 'verification': 'visual_depth'})]
    assert out['behavior_result']['status'] == 'planning_only'
    assert out['behavior_result']['executed'] is False
    assert 'you do not control joints, servos, pwm, can' in llm.extra.lower()
    assert 'planning_only' in llm.extra.lower()


def test_look_at_this_remains_visual_question_not_motion_request():
    router = InteractionActionRouter({'enabled': True, 'auto_vision': True})
    decision = router.route('Look at this.', language='en')
    assert decision.use_vision is True
    assert decision.behavior_intent is None


def test_explicit_head_turn_is_semantic_look_at_behavior():
    router = InteractionActionRouter({'enabled': True, 'auto_vision': True})
    decision = router.route('Turn your head toward the clock.', language='en')
    assert decision.behavior_intent == 'look_at'
    assert decision.behavior_parameters['target'] == 'clock'
    assert decision.requires_deep is True


def test_force_temporal_observation_does_not_require_keyword():
    pi = Pi()
    out = _conv(pi=pi).handle_text('Analyze this motion.', language='en', force_temporal_vision=True)
    assert pi.observe_calls == 1
    assert out['temporal_observation'] is True
    assert out['automatic_vision'] is False
    assert out['reasoning_mode'] == 'fast'
