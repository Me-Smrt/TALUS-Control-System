from __future__ import annotations

"""Print a compact summary of robot frames without opening Blender."""

import argparse
import json
import socket


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    args = p.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.host, args.port))
    print(f"Listening on udp://{args.host}:{args.port}")
    try:
        while True:
            data, _ = sock.recvfrom(65535)
            frame = json.loads(data.decode("utf-8"))
            robot = frame.get("robot", {})
            tracking = frame.get("tracking", {})
            arms = robot.get("arms", {})
            print(
                f"t={frame.get('timestamp_s', 0):.3f} "
                f"face={tracking.get('face_valid')} body={tracking.get('body_valid')} "
                f"hands=({tracking.get('left_hand_valid')},{tracking.get('right_hand_valid')}) "
                f"arm_err_mm=({arms.get('left', {}).get('wrist_error_mm', float('nan')):.1f},"
                f"{arms.get('right', {}).get('wrist_error_mm', float('nan')):.1f})"
            )
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()


if __name__ == "__main__":
    main()
