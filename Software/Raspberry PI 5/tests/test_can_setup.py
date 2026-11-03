from pathlib import Path
from types import SimpleNamespace
import pytest

from automaton.can_setup import configure_all, configure_interface, list_states


class FakeRunner:
    def __init__(self):
        self.calls = []
    def __call__(self, args, **kwargs):
        self.calls.append(list(args))
        return SimpleNamespace(stdout="[]", returncode=0)


def test_configure_interface_uses_runtime_bitrate():
    r = FakeRunner()
    configure_interface("can4", 250_000, 123, runner=r)
    assert r.calls == [
        ["ip", "link", "set", "dev", "can4", "down"],
        ["ip", "link", "set", "dev", "can4", "type", "can", "bitrate", "250000", "restart-ms", "123"],
        ["ip", "link", "set", "dev", "can4", "up"],
    ]


def test_configure_all_can_tolerate_missing(tmp_path: Path):
    (tmp_path / "can0").mkdir()
    (tmp_path / "can0" / "operstate").write_text("down\n")
    r = FakeRunner()
    configured = configure_all(["can0", "can1"], 500_000, runner=r, require_all=False, sys_class_net=tmp_path)
    assert configured == ["can0"]
    states = list_states(["can0", "can1"], tmp_path)
    assert states[0].exists and states[0].operstate == "down"
    assert not states[1].exists


def test_configure_all_requires_present_interfaces(tmp_path: Path):
    with pytest.raises(RuntimeError, match="missing SocketCAN interfaces"):
        configure_all(["can0"], 500_000, runner=FakeRunner(), require_all=True, sys_class_net=tmp_path)
