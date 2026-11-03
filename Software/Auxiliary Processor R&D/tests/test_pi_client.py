import unittest
from unittest import mock

from aux_core.pi_client import PiClient


class PiClientCameraTests(unittest.TestCase):
    def test_falls_back_to_live_aurora_when_config_names_do_not_match(self):
        client = PiClient({
            "base_url": "http://127.0.0.1:8766",
            "default_camera": "tracking",
            "visual_camera_preference": ["eye", "tracking"],
        })
        camera_payload = {
            "cameras": {
                "aurora": {"id": "aurora", "role": "tracking", "enabled": True, "status": "online"},
                "eye": {"id": "eye", "enabled": False, "status": "configured_disabled"},
            },
            "frames": {"aurora": {"raw": {"sequence": 10}}},
        }
        with mock.patch.object(client, "cameras", return_value=camera_payload), \
             mock.patch.object(client, "state", return_value={"perception": {"tracking_camera_id": "aurora"}}):
            self.assertEqual(client.choose_camera(), "aurora")

    def test_preferred_online_eye_wins(self):
        client = PiClient({"default_camera": "aurora", "visual_camera_preference": ["eye", "aurora"]})
        payload = {
            "cameras": {
                "eye": {"enabled": True, "status": "online"},
                "aurora": {"enabled": True, "status": "online", "role": "tracking"},
            },
            "frames": {"eye": {"raw": {}}, "aurora": {"raw": {}}},
        }
        with mock.patch.object(client, "cameras", return_value=payload):
            self.assertEqual(client.choose_camera(), "eye")


class PiClientHealthTests(unittest.TestCase):
    def test_health_uses_lightweight_health_endpoint(self):
        client = PiClient({"base_url": "http://127.0.0.1:8766", "timeout_s": 1.25})
        with mock.patch("aux_core.pi_client.json_request", return_value=(200, {"status": "online"})) as request:
            payload = client.health()
        self.assertEqual(payload["status"], "online")
        request.assert_called_once_with(
            "http://127.0.0.1:8766/v1/health",
            headers={"Accept": "application/json"},
            timeout=1.25,
        )

    def test_environment_can_override_pi_base_url(self):
        with mock.patch.dict("os.environ", {"AUTOMATON_PI_API_BASE": "http://192.168.50.20:8766"}):
            client = PiClient({
                "base_url": "http://127.0.0.1:8766",
                "base_url_env": "AUTOMATON_PI_API_BASE",
            })
        self.assertEqual(client.base, "http://192.168.50.20:8766")


class PiLinkMonitorTests(unittest.TestCase):
    def test_monitor_publishes_only_link_transitions(self):
        from aux_core.pi_client import PiLinkMonitor

        client = mock.Mock()
        client.health.side_effect = [
            {"status": "online"},
            {"status": "online"},
            OSError("connection refused"),
        ]
        events = []
        monitor = PiLinkMonitor(client, lambda status, detail: events.append((status, detail)), period_s=2.0)

        self.assertEqual(monitor.probe_once(), "online")
        self.assertEqual(monitor.probe_once(), "online")
        self.assertEqual(monitor.probe_once(), "offline")

        self.assertEqual(events[0], ("online", None))
        self.assertEqual(events[1][0], "offline")
        self.assertIn("connection refused", events[1][1])
        self.assertEqual(len(events), 2)

if __name__ == "__main__":
    unittest.main()
