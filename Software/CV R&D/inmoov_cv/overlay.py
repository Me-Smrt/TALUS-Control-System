from __future__ import annotations

import math
from typing import Iterable

import cv2
import numpy as np

from .body import BodyState
from .face import FaceState
from .hands import HandState


POSE_CONNECTIONS = [
    (11,12),(11,13),(13,15),(12,14),(14,16),
    (11,23),(12,24),(23,24),(23,25),(25,27),(24,26),(26,28),
    (27,29),(29,31),(28,30),(30,32),
]
HAND_CONNECTIONS = [
    (0,1),(1,2),(2,3),(3,4),
    (0,5),(5,6),(6,7),(7,8),
    (5,9),(9,10),(10,11),(11,12),
    (9,13),(13,14),(14,15),(15,16),
    (13,17),(17,18),(18,19),(19,20),(0,17),
]

# MediaPipe anatomical eye corners.  Left/right always mean the tracked
# person's anatomical sides, never screen-left/screen-right.
LEFT_EYE_CORNERS = (263, 362)
RIGHT_EYE_CORNERS = (33, 133)


def _xy(point: list[float], width: int, height: int, mirror: bool) -> tuple[int, int]:
    x, y = float(point[0]), float(point[1])
    if mirror:
        x = 1.0 - x
    return int(x * width), int(y * height)


def _draw_chain(image: np.ndarray, points: list[list[float]], connections: Iterable[tuple[int,int]], mirror: bool, thickness: int = 2) -> None:
    h, w = image.shape[:2]
    for a, b in connections:
        if a >= len(points) or b >= len(points):
            continue
        cv2.line(image, _xy(points[a], w, h, mirror), _xy(points[b], w, h, mirror), (200, 200, 200), thickness, cv2.LINE_AA)
    for p in points:
        x, y = _xy(p, w, h, mirror)
        if -10 <= x <= w + 10 and -10 <= y <= h + 10:
            cv2.circle(image, (x, y), 2, (255, 255, 255), -1, cv2.LINE_AA)


def draw_overlay(
    frame_bgr: np.ndarray,
    body: BodyState,
    hands: dict[str, HandState],
    face: FaceState,
    robot_frame: dict,
    *,
    mirror_preview: bool = True,
    fps: float = 0.0,
) -> np.ndarray:
    image = cv2.flip(frame_bgr, 1) if mirror_preview else frame_bgr.copy()
    h, w = image.shape[:2]

    if body.valid:
        _draw_chain(image, body.normalized_landmarks, POSE_CONNECTIONS, mirror_preview)
    for side_name, hand in hands.items():
        if hand.valid:
            _draw_chain(image, hand.normalized_landmarks, HAND_CONNECTIONS, mirror_preview)
            if hand.normalized_landmarks:
                hx, hy = _xy(hand.normalized_landmarks[0], w, h, mirror_preview)
                label = "L HAND" if side_name == "left" else "R HAND"
                cv2.putText(image, label, (hx + 5, hy - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255,255,255), 1, cv2.LINE_AA)

    if face.valid and face.normalized_landmarks:
        for idx in range(0, len(face.normalized_landmarks), 5):
            x, y = _xy(face.normalized_landmarks[idx], w, h, mirror_preview)
            cv2.circle(image, (x, y), 1, (180, 180, 180), -1)

        for side, corners, gx, gy in (
            ("L", LEFT_EYE_CORNERS, face.left_gaze_x, face.left_gaze_y),
            ("R", RIGHT_EYE_CORNERS, face.right_gaze_x, face.right_gaze_y),
        ):
            if max(corners) < len(face.normalized_landmarks):
                a = np.asarray(face.normalized_landmarks[corners[0]][:2])
                b = np.asarray(face.normalized_landmarks[corners[1]][:2])
                center = ((a + b) * 0.5).tolist() + [0.0]
                start = _xy(center, w, h, mirror_preview)
                dx = int(gx * 35.0 * (-1 if mirror_preview else 1))
                dy = int(-gy * 35.0)
                cv2.arrowedLine(image, start, (start[0] + dx, start[1] + dy), (255, 255, 255), 2, cv2.LINE_AA, tipLength=0.25)
                cv2.putText(image, side, (start[0] + 4, start[1] - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255,255,255), 1, cv2.LINE_AA)

    raw_robot = robot_frame.get("robot", {})
    sim_robot = robot_frame.get("simulation", raw_robot)
    torso = raw_robot.get("torso", {})
    sim_torso = sim_robot.get("torso", torso)
    face_cmd = raw_robot.get("face", {})
    sim_face = sim_robot.get("face", face_cmd)
    left_arm = raw_robot.get("arms", {}).get("left", {})
    right_arm = raw_robot.get("arms", {}).get("right", {})

    lines = [
        f"FPS {fps:5.1f}   q/ESC quit   c face-neutral   w wrist-neutral   r reset   e eye-test   L/R=person anatomy",
        f"Face {'OK' if face.valid else '--'}  Body {'OK' if body.valid else '--'}  Hands L:{'OK' if hands['left'].valid else '--'} R:{'OK' if hands['right'].valid else '--'}",
    ]
    if torso.get("valid"):
        lines.append(
            f"Torso target yaw/side {math.degrees(torso['yaw_rad']):+5.1f}/{math.degrees(torso['bend_rad']):+5.1f}  "
            f"sim {math.degrees(sim_torso.get('yaw_rad',0.0)):+5.1f}/{math.degrees(sim_torso.get('bend_rad',0.0)):+5.1f}  "
            f"sagittal(unapplied) {math.degrees(torso.get('tracked_sagittal_lean_rad',0.0)):+5.1f} deg"
        )
    if face_cmd.get("valid"):
        head = face_cmd["head"]
        eyelids = face_cmd["eyelids"]
        eyes = face_cmd.get("eyes", {})
        le, re = eyes.get("left", {}), eyes.get("right", {})
        sle = sim_face.get("eyes", {}).get("left", le)
        sre = sim_face.get("eyes", {}).get("right", re)
        lines.append(
            f"Head turn/nod/tilt {math.degrees(head['turn_rad']):+5.1f}/{math.degrees(head['nod_rad']):+5.1f}/{math.degrees(head['tilt_rad']):+5.1f} deg  lids {eyelids['left_closed']:.2f}/{eyelids['right_closed']:.2f}"
        )
        lines.append(
            f"Eyes target L {math.degrees(le.get('pan_rad',0.0)):+4.1f}/{math.degrees(le.get('tilt_rad',0.0)):+4.1f}  "
            f"R {math.degrees(re.get('pan_rad',0.0)):+4.1f}/{math.degrees(re.get('tilt_rad',0.0)):+4.1f} deg | "
            f"sim L {math.degrees(sle.get('pan_rad',0.0)):+4.1f} R {math.degrees(sre.get('pan_rad',0.0)):+4.1f}"
            + ("  [EYE TEST]" if face_cmd.get("eye_test_enabled") else "")
        )
    if left_arm.get("valid") or right_arm.get("valid"):
        lines.append(
            f"IK wrist err mm  L:{left_arm.get('wrist_error_mm', float('nan')):5.1f}  R:{right_arm.get('wrist_error_mm', float('nan')):5.1f}"
        )

    hands_cmd = raw_robot.get("hands", {})
    wrist_bits = []
    for side in ("left", "right"):
        wrist = hands_cmd.get(side, {}).get("wrist", {})
        if wrist.get("valid"):
            wrist_bits.append(
                f"{side[0].upper()} rot {math.degrees(wrist.get('rotation_rad',0.0)):+5.1f} bend {math.degrees(wrist.get('bend_rad',0.0)):+5.1f}"
                + ("*" if wrist.get("negative_bend_unrepresentable") else "")
            )
    if wrist_bits:
        lines.append("Wrists " + " | ".join(wrist_bits) + "   (* human extension not representable by current 0..90 bend joint)")

    y = 24
    for line in lines:
        cv2.putText(image, line, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(image, line, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (255, 255, 255), 1, cv2.LINE_AA)
        y += 21

    return image
