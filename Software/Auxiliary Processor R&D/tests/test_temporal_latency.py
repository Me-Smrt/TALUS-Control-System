from aux_core.action_router import InteractionActionRouter
from aux_core.reasoning import ThinkingCueSequence


def test_temporal_motion_question_is_multiframe_but_not_implicitly_deep():
    router = InteractionActionRouter({"enabled": True, "auto_vision": True})
    d = router.route("What does it look like I'm doing?", language="en")
    assert d.temporal_vision is True
    assert d.requires_deep is False


def test_force_observe_is_not_implicitly_deep():
    router = InteractionActionRouter({"enabled": True, "auto_vision": True})
    d = router.route("Analyze this motion", language="en", force_temporal_vision=True)
    assert d.temporal_vision is True
    assert d.requires_deep is False


def test_behavior_planning_still_requires_deep():
    router = InteractionActionRouter({"enabled": True, "auto_vision": True})
    d = router.route("Point at the clock", language="en")
    assert d.behavior_intent == "point_at"
    assert d.requires_deep is True


def test_legacy_dense_cues_are_clamped_to_conversational_spacing():
    cues = ThinkingCueSequence({
        "initial_wait_s": 4.0,
        "repeat_wait_s": 9.0,
        "max_wait_cues": 4,
        "waiting_lines": ["a", "b"],
    })
    # Raw schedule remains configurable for diagnostics/tests. The conversation
    # path requests a calmer minimum spoken cadence without rewriting user config.
    raw = list(cues.schedule())
    assert raw[0][0] == 4.0
    schedule = list(cues.schedule(min_initial_s=6.0, min_repeat_s=15.0))
    assert schedule[0][0] >= 6.0
    assert all((b[0] - a[0]) >= 15.0 for a, b in zip(schedule, schedule[1:]))
