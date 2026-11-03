from inmoov_cv.overlay import LEFT_EYE_CORNERS, RIGHT_EYE_CORNERS


def test_mediapipe_anatomical_eye_indices_are_not_swapped():
    assert LEFT_EYE_CORNERS == (263, 362)
    assert RIGHT_EYE_CORNERS == (33, 133)


def test_preview_and_input_mirror_settings_are_distinct_in_default_config():
    import json
    from pathlib import Path
    cfg = json.loads((Path(__file__).parents[1] / "config" / "default.json").read_text())
    assert cfg["camera"]["mirror_preview"] is True
    assert cfg["camera"].get("input_mirrored", False) is False
    assert cfg["retarget"]["mirror_motion"] is False
