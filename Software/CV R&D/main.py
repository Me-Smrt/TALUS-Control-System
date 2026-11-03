from __future__ import annotations

"""Main Raspberry Pi perception / IK control-plane entry point.

The file remains intentionally small enough to be the one thing you run.  The
MediaPipe/IK implementation lives in ``inmoov_cv``; Raspberry Pi ownership of
state, camera snapshots, health, and the future auxiliary-node API lives in
``inmoov_pi``.
"""

import argparse
import copy
import math
import sys
import time
from pathlib import Path

import cv2

from inmoov_cv.body import BodyAnalyzer
from inmoov_cv.face import FaceAnalyzer
from inmoov_cv.hands import HandAnalyzer
from inmoov_cv.overlay import draw_overlay
from inmoov_cv.recording import JsonlRecorder
from inmoov_cv.retarget import RobotRetargeter
from inmoov_cv.schema import perception_to_dict
from inmoov_cv.simulation import SimulationMotionAdapter
from inmoov_cv.tracker import HolisticTracker
from inmoov_cv.transport import UdpJsonPublisher
from inmoov_cv.util import load_json
from inmoov_pi.api_server import ControlApiServer
from inmoov_pi.audio import AudioDeviceProbe
from inmoov_pi.behavior import BehaviorBroker
from inmoov_pi.frame_store import LatestFrameStore
from inmoov_pi.secondary_camera import SecondaryCameraWorker
from inmoov_pi.state import RobotStateHub
from inmoov_pi.system_health import SystemHealthSampler
from inmoov_pi.sim_gestures import BlenderGestureController


ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "config" / "default.json"
KINEMATICS_CONFIG = ROOT / "config" / "inmoov_kinematics.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="InMoov Raspberry Pi perception + IK control plane")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--camera", type=int, default=None, help="Tracking camera index; defaults to config value")
    source.add_argument("--video", type=Path, help="Use a video file instead of the tracking camera")
    parser.add_argument("--no-bridge", action="store_true", help="Do not send UDP frames to Blender")
    parser.add_argument("--no-preview", action="store_true", help="Run without an OpenCV window")
    parser.add_argument("--no-api", action="store_true", help="Disable the read-only Pi state/camera HTTP API")
    parser.add_argument("--record", type=Path, help="Write full perception + robot output to JSONL")
    parser.add_argument("--mirror-motion", action="store_true", help="Swap left/right and mirror horizontal motion")
    return parser.parse_args()


def open_source(args: argparse.Namespace, config: dict) -> tuple[cv2.VideoCapture, bool]:
    if args.video:
        cap = cv2.VideoCapture(str(args.video))
        is_video = True
    else:
        camera_index = int(config["camera"]["index"] if args.camera is None else args.camera)
        if sys.platform == "win32" and hasattr(cv2, "CAP_DSHOW"):
            cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
        else:
            cap = cv2.VideoCapture(camera_index)
        is_video = False
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(config["camera"].get("width", 1280)))
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(config["camera"].get("height", 720)))
        cap.set(cv2.CAP_PROP_FPS, int(config["camera"].get("fps", 30)))
    if not cap.isOpened():
        raise RuntimeError("Could not open the requested tracking camera/video source")
    return cap, is_video


def main() -> int:
    args = parse_args()
    config = load_json(args.config)
    if args.mirror_motion:
        config = copy.deepcopy(config)
        config["retarget"]["mirror_motion"] = True

    camera_cfg = config["camera"]
    tracking_camera_id = str(camera_cfg.get("id", "tracking"))
    tracking_camera_label = str(camera_cfg.get("label", "Tracking camera"))

    state = RobotStateHub(
        version="0.3.0",
        planned_auxiliary=str(config.get("auxiliary", {}).get("planned_type", "Jetson Orin Nano")),
    )
    frames = LatestFrameStore()
    health_sampler = SystemHealthSampler()
    audio_probe = AudioDeviceProbe(config.get("audio", {}))
    behavior_cfg = config.get("behavior", {})
    # This backend sends poses ONLY into Blender's existing UDP visualization.
    # Explicit simulation_only mode cannot reach hardware/CAN/PWM.
    gesture_backend = BlenderGestureController(load_json(KINEMATICS_CONFIG),
                             config.get('collision_guard', {})) if behavior_cfg.get('mode') == 'simulation_only' else None
    behavior_broker = BehaviorBroker(
        controller=gesture_backend,
        planning_only=(gesture_backend is None),
        default_ttl_ms=int(behavior_cfg.get("default_ttl_ms", 5000)),
        max_ttl_ms=int(behavior_cfg.get("max_ttl_ms", 15000)),
        max_records=int(behavior_cfg.get("max_records", 128)),
    ) if bool(behavior_cfg.get("enabled", True)) else None

    # Pre-populate dashboard-visible camera inventory even when hardware is not
    # present yet.  This keeps "planned" distinct from "online".
    state.update_camera(
        tracking_camera_id,
        label=tracking_camera_label,
        role="tracking",
        enabled=True,
        status="starting",
        processed_available=True,
        planned_hardware=camera_cfg.get("planned_hardware"),
    )
    secondary_workers: list[SecondaryCameraWorker] = []
    for extra in config.get("additional_cameras", []):
        cid = str(extra.get("id", "camera"))
        enabled = bool(extra.get("enabled", False))
        state.update_camera(
            cid,
            label=str(extra.get("label", cid)),
            role=str(extra.get("role", "secondary")),
            enabled=enabled,
            status="starting" if enabled else "configured_disabled",
            processed_available=False,
            planned_hardware=extra.get("planned_hardware"),
        )
        if enabled:
            secondary_workers.append(SecondaryCameraWorker(extra, frames, state))

    api: ControlApiServer | None = None
    api_cfg = config.get("control_api", {})
    if bool(api_cfg.get("enabled", True)) and not args.no_api:
        api = ControlApiServer(
            api_cfg, state, frames,
            behaviors=behavior_broker,
            observation_config=config.get("temporal_observation", {}),
        )
        api.start()
        print(f"[PI] State/camera + semantic behavior API: http://{api.host}:{api.port}/v1/state")

    for worker in secondary_workers:
        worker.start()

    face_analyzer = FaceAnalyzer(config["retarget"].get("head_neutral_calibration_frames", 30))
    body_analyzer = BodyAnalyzer()
    hand_analyzer = HandAnalyzer()
    retargeter = RobotRetargeter(config, KINEMATICS_CONFIG)
    simulation = SimulationMotionAdapter(config)
    simulation.configure_collision(KINEMATICS_CONFIG, config.get("collision_guard", {}))

    bridge_cfg = config["bridge"]
    publisher = None
    if bool(bridge_cfg.get("enabled", True)) and not args.no_bridge:
        publisher = UdpJsonPublisher(
            bridge_cfg.get("host", "127.0.0.1"),
            int(bridge_cfg.get("port", 8765)),
            int(bridge_cfg.get("max_datagram_bytes", 60000)),
        )

    record_path = args.record
    if record_path is None and bool(config.get("recording", {}).get("enabled", False)):
        record_path = ROOT / config["recording"]["path"]
    recorder = JsonlRecorder(record_path if record_path.is_absolute() else ROOT / record_path) if record_path else None

    cap, is_video = open_source(args, config)
    mirror_preview = bool(camera_cfg.get("mirror_preview", True))
    input_mirrored = bool(camera_cfg.get("input_mirrored", False))
    snapshots_enabled = bool(config.get("frame_service", {}).get("processed_snapshots", True))
    video_fps = float(cap.get(cv2.CAP_PROP_FPS))
    if not math.isfinite(video_fps) or video_fps <= 1.0:
        video_fps = 30.0
    frame_index = 0
    last_mp_timestamp_ms = -1
    last_wall = time.perf_counter()
    display_fps = 0.0
    next_health = 0.0
    next_audio = 0.0

    state.set_system_status("online")
    state.update_audio(audio_probe.probe())

    print("[CV] Starting. Keep a neutral forward-facing pose for the first second so head neutral can calibrate.")
    print(
        f"[CV] handedness: input_mirrored={input_mirrored} "
        f"preview_mirrored={mirror_preview} "
        f"retarget_mirror={bool(config.get('retarget', {}).get('mirror_motion', False))}"
    )
    print("[CV] Keys: q/ESC quit | c face neutral | w wrist neutral | r reset smoothing/profile | e eye diagnostic sweep")
    print("[PI] Camera frames are retained locally and encoded only when a client requests a snapshot.")

    try:
        with HolisticTracker(config["mediapipe"], ROOT) as tracker:
            while True:
                ok, frame = cap.read()
                if not ok:
                    break

                # Normalize camera handedness once at the acquisition boundary.
                # Downstream CV/IK always sees canonical, non-mirrored camera
                # coordinates.  mirror_preview is display-only and mirror_motion
                # is a separate intentional retargeting choice.
                if input_mirrored:
                    frame = cv2.flip(frame, 1)

                capture_mono_ns = time.monotonic_ns()
                capture_unix_ns = time.time_ns()
                raw_meta = frames.publish_raw(
                    tracking_camera_id,
                    frame,
                    sequence=frame_index + 1,
                    monotonic_ns=capture_mono_ns,
                    unix_ns=capture_unix_ns,
                )
                state.update_camera(
                    tracking_camera_id,
                    status="online",
                    error=None,
                    sequence=raw_meta.sequence,
                    width=raw_meta.width,
                    height=raw_meta.height,
                    captured_monotonic_ns=raw_meta.captured_monotonic_ns,
                    captured_unix_ns=raw_meta.captured_unix_ns,
                    processed_available=True,
                )

                now = time.perf_counter()
                if is_video:
                    pos_ms = cap.get(cv2.CAP_PROP_POS_MSEC)
                    proposed = int(round(pos_ms)) if pos_ms > 0 else int(round(frame_index * 1000.0 / video_fps))
                else:
                    proposed = int(round(now * 1000.0))
                timestamp_ms = max(last_mp_timestamp_ms + 1, proposed)
                last_mp_timestamp_ms = timestamp_ms
                timestamp_s = timestamp_ms / 1000.0

                result = tracker.detect(frame, timestamp_ms)
                face = face_analyzer.analyze(result, frame.shape)
                body = body_analyzer.analyze(result)
                hands = hand_analyzer.analyze(result)
                perception = perception_to_dict(face, body, hands)
                robot_frame = retargeter.retarget(timestamp_s, face, body, hands)
                if gesture_backend is not None:
                    robot_frame = gesture_backend.apply(robot_frame)
                # Authoritative CV/IK targets stay under robot_frame["robot"].
                # Blender consumes the separate servo-like profiled copy.
                robot_frame["simulation"] = simulation.adapt(robot_frame)

                dt = max(now - last_wall, 1e-6)
                instant_fps = 1.0 / dt
                display_fps = instant_fps if display_fps <= 0 else (0.90 * display_fps + 0.10 * instant_fps)
                last_wall = now

                if publisher:
                    publisher.send(robot_frame)

                if recorder:
                    recorder.write(
                        {
                            "schema": "inmoov.cv_ik.recording.v3",
                            "timestamp_s": timestamp_s,
                            "capture_monotonic_ns": capture_mono_ns,
                            "capture_unix_ns": capture_unix_ns,
                            "camera_id": tracking_camera_id,
                            "perception": perception,
                            "retarget": robot_frame,
                        }
                    )

                processed = None
                if snapshots_enabled or not args.no_preview:
                    processed = draw_overlay(
                        frame,
                        body,
                        hands,
                        face,
                        robot_frame,
                        mirror_preview=mirror_preview,
                        fps=display_fps,
                    )
                    frames.publish_processed(
                        tracking_camera_id,
                        processed,
                        sequence=raw_meta.sequence,
                        monotonic_ns=capture_mono_ns,
                        unix_ns=capture_unix_ns,
                    )

                state.update_perception(
                    perception,
                    robot_frame,
                    fps=display_fps,
                    camera_id=tracking_camera_id,
                    monotonic_ns=capture_mono_ns,
                    unix_ns=capture_unix_ns,
                    frame_sequence=raw_meta.sequence,
                )

                if now >= next_health:
                    state.update_health(health_sampler.sample())
                    next_health = now + float(config.get("state", {}).get("health_period_s", 1.0))
                if now >= next_audio:
                    state.update_audio(audio_probe.probe())
                    next_audio = now + float(config.get("state", {}).get("audio_probe_period_s", 10.0))

                if not args.no_preview:
                    preview = processed if processed is not None else frame
                    cv2.imshow("InMoov CV + IK / Pi Control Plane", preview)
                    key = cv2.waitKey(1) & 0xFF
                    if key in (27, ord("q")):
                        break
                    if key == ord("c"):
                        face_analyzer.reset_neutral()
                        print("[CV] Face neutral calibration reset")
                    if key == ord("w"):
                        retargeter.reset_wrist_neutral()
                        print("[CV] Wrist neutral calibration reset; hold a comfortable straight-wrist pose briefly")
                    if key == ord("e"):
                        enabled = retargeter.toggle_eye_test()
                        print(f"[CV] Eye diagnostic sweep {'ENABLED' if enabled else 'disabled'}")
                    if key == ord("r"):
                        retargeter.reset_filters()
                        simulation.reset()
                        print("[CV] Motion smoothing / IK warm-start / simulation profile state reset")

                frame_index += 1
    finally:
        state.mark_perception_stopped("stopped")
        state.set_system_status("stopping")
        cap.release()
        cv2.destroyAllWindows()
        for worker in secondary_workers:
            worker.stop()
        if api:
            api.stop()
        if publisher:
            publisher.close()
        if recorder:
            recorder.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
