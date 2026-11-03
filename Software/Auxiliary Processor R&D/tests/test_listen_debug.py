from aux_core.audio_loop import AudioConversationLoop


def _loop(debug=True):
    return AudioConversationLoop({}, None, None, None, None, None, None, debug=debug)


def test_listen_debug_prints_stt_transcript_and_language(capsys):
    loop = _loop(True)
    loop._debug_stt({"text": "Hey Talos", "language": "en", "language_probability": 0.987})
    out = capsys.readouterr().out
    assert "you> Hey Talos" in out
    assert "STT language=en" in out
    assert "confidence=99%" in out


def test_listen_debug_prints_ignored_engagement_reason(capsys):
    loop = _loop(True)
    loop._debug_engagement({
        "accept": False,
        "score": 0.18,
        "reason": "face_visible",
    })
    out = capsys.readouterr().out
    assert "engagement=ignored" in out
    assert "score=0.18" in out
    assert "reason=face_visible" in out


def test_listen_debug_prints_wake_and_turn_diagnostics(capsys):
    loop = _loop(True)
    loop._debug_engagement({
        "accept": True,
        "score": 1.0,
        "reason": "wake_phrase",
        "wake": {
            "raw_alias": "talos",
            "canonical": "TALUS",
            "kind": "wake_name_bare",
        },
    })
    loop._debug_turn_diagnostics({
        "reasoning_mode": "fast",
        "reasoning_reason": "default_fast",
        "reasoning_score": 0.0,
        "actions": ["vision"],
        "automatic_vision": True,
        "visual_reason": "visual_question",
        "camera_id": "aurora",
    })
    out = capsys.readouterr().out
    assert "engagement=accepted" in out
    assert "talos -> TALUS" in out
    assert "reasoning=fast" in out
    assert "automatic actions=vision" in out
    assert "camera=aurora" in out


def test_deployment_audio_loop_debug_helpers_are_silent(capsys):
    loop = _loop(False)
    loop._debug_stt({"text": "Hey Talos", "language": "en", "language_probability": 1.0})
    loop._debug_engagement({"accept": False, "score": 0.0, "reason": "ignored"})
    loop._debug_turn_diagnostics({"reasoning_mode": "fast"})
    assert capsys.readouterr().out == ""


def test_listen_debug_reports_engagement_refresh(capsys):
    class E:
        cfg = {"active_window_s": 25}
        def touch(self):
            return 123.0
    loop = _loop(True)
    loop.engagement = E()
    loop._refresh_engagement_after_reply()
    out = capsys.readouterr().out
    assert "engagement=active_window" in out
    assert "refreshed=25s" in out
