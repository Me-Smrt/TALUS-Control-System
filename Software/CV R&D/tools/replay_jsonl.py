from __future__ import annotations

"""Replay a recorded session's robot frames to the Blender UDP bridge."""

import argparse
import json
import socket
import time
from pathlib import Path


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("path", type=Path)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--speed", type=float, default=1.0, help="1=real time, 0.5=half speed, 2=double speed")
    p.add_argument("--loop", action="store_true")
    return p.parse_args()


def load_frames(path: Path):
    frames = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            robot = row.get("retarget")
            if robot:
                frames.append(robot)
    if not frames:
        raise RuntimeError("No recorded retarget frames found")
    return frames


def play(frames, sock, address, speed):
    speed = max(0.01, speed)
    first_ts = float(frames[0].get("timestamp_s", 0.0))
    start = time.perf_counter()
    for frame in frames:
        target = (float(frame.get("timestamp_s", first_ts)) - first_ts) / speed
        while True:
            remaining = target - (time.perf_counter() - start)
            if remaining <= 0:
                break
            time.sleep(min(remaining, 0.005))
        sock.sendto(json.dumps(frame, separators=(",", ":")).encode("utf-8"), address)


def main():
    args = parse_args()
    frames = load_frames(args.path)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        while True:
            play(frames, sock, (args.host, args.port), args.speed)
            if not args.loop:
                break
    finally:
        sock.close()


if __name__ == "__main__":
    main()
