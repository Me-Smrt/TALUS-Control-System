from aux_core.engagement import EngagementManager


def _cfg():
    return {
        "enabled": True,
        "wake_phrases": ["hey robot"],
        "wake_name": "TALUS",
        "wake_name_aliases": ["talus", "talos"],
        "wake_name_prefixes": ["hey", "ok", "okay"],
        "allow_bare_wake_name": True,
        "active_window_s": 25,
        "idle_accept_score": 0.72,
        "wake_score": 1.0,
        "face_score": 0.18,
        "head_attention_score": 0.28,
        "gaze_attention_score": 0.36,
        "head_yaw_limit_deg": 28,
        "head_pitch_limit_deg": 24,
        "gaze_pan_limit": 0.35,
        "gaze_tilt_limit": 0.35,
    }


def test_face_plus_head_is_direct_address_without_gaze():
    mgr = EngagementManager(_cfg())
    state = {"perception": {
        "face": True,
        "head_pose_rad": {"yaw": 0.0, "pitch": 0.0, "roll": 0.0},
        "gaze": {},
    }}
    result = mgr.evaluate("I am still talking to you", state, now=100.0)
    assert result["accept"] is True
    assert result["score"] == 0.46
    assert result["accept_basis"] == "face_head_direct_address"


def test_face_only_still_does_not_reenter_idle_conversation():
    mgr = EngagementManager(_cfg())
    state = {"perception": {
        "face": True,
        "head_pose_rad": {"yaw": 1.2, "pitch": 0.0, "roll": 0.0},
        "gaze": {},
    }}
    result = mgr.evaluate("background conversation", state, now=100.0)
    assert result["accept"] is False


def test_touch_restarts_window_after_robot_reply():
    mgr = EngagementManager(_cfg())
    first = mgr.evaluate("hey talus hello", {}, now=10.0)
    assert first["accept"]
    # Pretend inference/TTS consumed the original 25-second window.
    mgr.touch(now=45.0)
    followup = mgr.evaluate("and one more thing", {}, now=60.0)
    assert followup["accept"] is True
    assert followup["reason"] == "active_conversation"


def test_head_direct_address_can_be_disabled_explicitly():
    cfg = _cfg()
    cfg["head_attention_direct_address"] = False
    mgr = EngagementManager(cfg)
    state = {"perception": {
        "face": True,
        "head_pose_rad": {"yaw": 0.0, "pitch": 0.0, "roll": 0.0},
        "gaze": {},
    }}
    result = mgr.evaluate("hello", state, now=100.0)
    assert result["accept"] is False
