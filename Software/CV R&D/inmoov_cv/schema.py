from __future__ import annotations

from .body import BodyState
from .face import FaceState
from .hands import HandState


def perception_to_dict(face: FaceState, body: BodyState, hands: dict[str, HandState]) -> dict:
    return {
        "face": {
            "valid": face.valid,
            "head_pose_rad": {
                "yaw": face.yaw_rad,
                "pitch": face.pitch_rad,
                "roll": face.roll_rad,
            },
            "eyelids_closed": {
                "left": face.left_eyelid_closed,
                "right": face.right_eyelid_closed,
            },
            "gaze": {
                "left": [face.left_gaze_x, face.left_gaze_y],
                "right": [face.right_gaze_x, face.right_gaze_y],
            },
            "jaw_open": face.jaw_open,
            "blendshapes": face.blendshapes,
            "normalized_landmarks": face.normalized_landmarks,
        },
        "body": {
            "valid": body.valid,
            "normalized_landmarks": body.normalized_landmarks,
            "world_landmarks_m": body.world_landmarks_m,
            "visibility": body.visibility,
            "joint_metrics_rad": body.joint_metrics_rad,
        },
        "hands": {
            side: {
                "valid": hand.valid,
                "normalized_landmarks": hand.normalized_landmarks,
                "world_landmarks_m": hand.world_landmarks_m,
                "curls": hand.curls,
                "palm_basis": hand.palm_basis,
            }
            for side, hand in hands.items()
        },
    }
