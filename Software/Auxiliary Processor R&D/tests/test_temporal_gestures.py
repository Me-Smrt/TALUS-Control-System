from aux_core.temporal_vision import summarize_motion


def _frame(x, y=0.25):
    def kp(px, py):
        return {"image_normalized": [px, py, 0.0]}
    return {
        "perception": {
            "body": {
                "keypoints": {
                    "right_wrist": kp(x, y),
                    "right_shoulder": kp(0.50, 0.50),
                    "left_wrist": kp(0.30, 0.60),
                    "left_shoulder": kp(0.30, 0.50),
                }
            },
            "face": {"head_pose_rad": {"yaw": 0.0}},
        }
    }


def test_repeated_raised_lateral_wrist_motion_is_exposed_to_qwen():
    manifest = {
        "actual_duration_ms": 1600,
        "frames": [_frame(x) for x in (0.35, 0.58, 0.36, 0.60, 0.37)],
        "depth": {"available": False},
    }
    text = summarize_motion(manifest)
    assert "right_wrist" in text
    assert "x-reversals=3" in text
    assert "dominant=horizontal" in text
    assert "raised=100%" in text
    assert "repeated-lateral=yes" in text
    assert "not an activity label" in text
