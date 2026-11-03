import io
import json
import threading
import time
import unittest
import urllib.request
import zipfile

import numpy as np

from inmoov_pi.api_server import ControlApiServer
from inmoov_pi.behavior import BehaviorBroker
from inmoov_pi.frame_store import LatestFrameStore
from inmoov_pi.state import RobotStateHub


class TemporalObservationApiTests(unittest.TestCase):
    def setUp(self):
        self.state = RobotStateHub(version="0.4.0")
        self.frames = LatestFrameStore()
        self.behaviors = BehaviorBroker(planning_only=True)
        self.server = ControlApiServer(
            {
                "bind_host": "127.0.0.1",
                "port": 0,
                "allow_unauthenticated_loopback": True,
                "jpeg_quality": 80,
            },
            self.state,
            self.frames,
            behaviors=self.behaviors,
            observation_config={
                "enabled": True,
                "default_duration_ms": 100,
                "default_samples": 3,
                "max_duration_ms": 1000,
                "max_samples": 6,
                "jpeg_quality": 75,
                "max_width": 64,
            },
        )
        self.server.start()
        self.base = f"http://127.0.0.1:{self.server.port}"

    def tearDown(self):
        self.server.stop()

    def _publish(self, seq: int):
        mono = time.monotonic_ns()
        unix = time.time_ns()
        frame = np.full((24, 32, 3), seq * 10, dtype=np.uint8)
        self.frames.publish_raw("aurora", frame, sequence=seq, monotonic_ns=mono, unix_ns=unix)
        self.state.update_perception(
            {
                "face": {"valid": True, "head_pose_rad": {"yaw": seq / 100.0}},
                "body": {
                    "valid": True,
                    "normalized_landmarks": [[0.0, 0.0, 0.0] for _ in range(33)],
                    "world_landmarks_m": [[0.0, 0.0, 0.0] for _ in range(33)],
                    "visibility": [1.0 for _ in range(33)],
                    "joint_metrics_rad": {},
                },
                "hands": {"left": {"valid": False}, "right": {"valid": False}},
            },
            {"timestamp_s": seq / 30.0, "robot": {}, "simulation": {}},
            fps=30.0,
            camera_id="aurora",
            monotonic_ns=mono,
            unix_ns=unix,
            frame_sequence=seq,
        )

    def test_temporal_observation_returns_chronological_zip(self):
        self._publish(1)

        def producer():
            time.sleep(0.06)
            self._publish(2)
            time.sleep(0.06)
            self._publish(3)

        thread = threading.Thread(target=producer, daemon=True)
        thread.start()
        with urllib.request.urlopen(
            self.base + "/v1/cameras/aurora/observe?duration_ms=120&samples=3&max_width=64",
            timeout=3,
        ) as response:
            data = response.read()
            self.assertEqual(response.headers["Content-Type"], "application/zip")
        thread.join(timeout=1)

        with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
            manifest = json.loads(zf.read("manifest.json"))
            self.assertEqual(manifest["schema"], "automaton.temporal_observation.v1")
            self.assertEqual(manifest["samples_captured"], 3)
            seqs = [x["sequence"] for x in manifest["frames"]]
            self.assertEqual(seqs, sorted(seqs))
            self.assertFalse(manifest["depth"]["available"])
            for item in manifest["frames"]:
                self.assertIn(item["file"], zf.namelist())

    def test_behavior_endpoint_is_planning_only(self):
        payload = {
            "schema": "automaton.aux_intent.v1",
            "intent": "point_at",
            "request_id": "req-test-1",
            "ttl_ms": 2500,
            "parameters": {"target": "clock", "arm": "auto", "verification": "visual_depth"},
        }
        req = urllib.request.Request(
            self.base + "/v1/behaviors",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=2) as response:
            result = json.load(response)
        self.assertEqual(result["intent"], "point_at")
        self.assertEqual(result["status"], "planning_only")
        self.assertFalse(result["executed"])

    def test_direct_joint_fields_are_rejected(self):
        payload = {
            "intent": "point_at",
            "request_id": "req-bad-1",
            "parameters": {"target": "clock", "joint_angle": 1.2},
        }
        req = urllib.request.Request(
            self.base + "/v1/behaviors",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(Exception):
            urllib.request.urlopen(req, timeout=2)


if __name__ == "__main__":
    unittest.main()
