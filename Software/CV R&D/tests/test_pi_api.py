import json
import unittest
import urllib.error
import urllib.request

import numpy as np

from inmoov_pi.api_server import ControlApiServer
from inmoov_pi.frame_store import LatestFrameStore
from inmoov_pi.state import RobotStateHub


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.state = RobotStateHub()
        self.frames = LatestFrameStore()
        self.server = ControlApiServer({
            "bind_host": "127.0.0.1",
            "port": 0,
            "allow_unauthenticated_loopback": True,
            "jpeg_quality": 80,
        }, self.state, self.frames)
        self.server.start()
        self.base = f"http://127.0.0.1:{self.server.port}"

    def tearDown(self):
        self.server.stop()

    def test_state_endpoint(self):
        with urllib.request.urlopen(self.base + "/v1/state", timeout=2) as response:
            payload = json.load(response)
        self.assertEqual(payload["schema"], "automaton.pi_state.v1")

    def test_frame_endpoint_is_snapshot_not_stream(self):
        self.frames.publish_raw("aurora", np.zeros((16, 24, 3), dtype=np.uint8))
        with urllib.request.urlopen(self.base + "/v1/cameras/aurora/frame?view=raw", timeout=2) as response:
            data = response.read()
            self.assertEqual(response.headers["Content-Type"], "image/jpeg")
            self.assertEqual(response.headers["X-Automaton-Camera"], "aurora")
        self.assertTrue(data.startswith(b"\xff\xd8"))


if __name__ == "__main__":
    unittest.main()
