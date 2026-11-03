from __future__ import annotations

"""Send obvious simulation-only sweeps to the Blender bridge.

Usage:
  python tools/blender_motion_diagnostic.py eyes
  python tools/blender_motion_diagnostic.py torso
  python tools/blender_motion_diagnostic.py wrists

Stop with Ctrl+C. This does not run CV or IK and is intended only to prove that
the expected Blender source joints visibly move.
"""

import argparse
import json
import math
import socket
import time


def base_robot() -> dict:
    return {
        "torso": {"valid": True, "yaw_rad": 0.0, "bend_rad": 0.0, "tracked_side_lean_rad": 0.0},
        "face": {
            "valid": True,
            "head": {"turn_rad": 0.0, "nod_rad": 0.0, "tilt_rad": 0.0},
            "eyes": {
                "left": {"pan_rad": 0.0, "tilt_rad": 0.0},
                "right": {"pan_rad": 0.0, "tilt_rad": 0.0},
            },
            "eye_test_enabled": True,
            "jaw_rad": 0.0,
            "eyelids": {"left_closed": 0.0, "right_closed": 0.0},
            "expression_blendshapes": {},
        },
        "arms": {"left": {"valid": False}, "right": {"valid": False}},
        "hands": {
            "left": {"valid": True, "curls": {}, "wrist": {"valid": True, "rotation_joint_name": "left_wrist_z", "bend_joint_name": "i01.leftHand.wrist.001", "rotation_rad": 0.0, "bend_rad": 0.0}},
            "right": {"valid": True, "curls": {}, "wrist": {"valid": True, "rotation_joint_name": "right_wrist_z", "bend_joint_name": "i01.rightHand.wrist.001", "rotation_rad": 0.0, "bend_rad": 0.0}},
        },
        "legs": {"applied": False},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=("eyes", "torso", "wrists"))
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    started = time.monotonic()
    print(f"[diagnostic] sweeping {args.mode}; Ctrl+C to stop")
    try:
        while True:
            elapsed = time.monotonic() - started
            robot = base_robot()
            s = math.sin(elapsed * 2.0 * math.pi * 0.20)
            s2 = math.sin(elapsed * 2.0 * math.pi * 0.13 + 0.8)
            if args.mode == "eyes":
                for eye in robot["face"]["eyes"].values():
                    eye["pan_rad"] = math.radians(16.0) * s
                    eye["tilt_rad"] = math.radians(22.0) * s2
            elif args.mode == "torso":
                robot["torso"]["yaw_rad"] = math.radians(30.0) * s
                robot["torso"]["bend_rad"] = math.radians(10.0) * s2
            elif args.mode == "wrists":
                for side in ("left", "right"):
                    robot["hands"][side]["wrist"]["rotation_rad"] = math.radians(70.0) * s
                    robot["hands"][side]["wrist"]["bend_rad"] = math.radians(35.0) * (0.5 + 0.5 * s2)

            packet = {
                "schema": "inmoov.cv_ik.poc.v2",
                "timestamp_s": time.time(),
                "robot": robot,
                "simulation": robot,
                "tracking": {},
            }
            sock.sendto(json.dumps(packet, separators=(",", ":")).encode("utf-8"), (args.host, args.port))
            time.sleep(1.0 / 30.0)
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
