from pathlib import Path
import pytest
from automaton.can_topology import discover_ccb_channels, ordered_interfaces, CanTopologyError


def _add_netdev(root: Path, name: str, target: Path):
    target.mkdir(parents=True, exist_ok=True)
    net = root / name
    net.mkdir(parents=True)
    (net / "device").symlink_to(target, target_is_directory=True)


def test_discovers_by_spi_chip_select_not_can_number(tmp_path: Path):
    sysnet = tmp_path / "sys" / "class" / "net"
    sysnet.mkdir(parents=True)
    devices = tmp_path / "devices"
    _add_netdev(sysnet, "can7", devices / "platform" / "spi0.0")
    _add_netdev(sysnet, "can1", devices / "platform" / "spi0.3")
    mapping = discover_ccb_channels(sysnet)
    assert mapping == {0: "can7", 3: "can1"}
    assert ordered_interfaces(mapping, require_all=False) == ("can7", "can1")


def test_requires_all_channels_when_requested():
    with pytest.raises(CanTopologyError, match="missing physical CCB CAN channels"):
        ordered_interfaces({0: "can4"}, expected_channels=2, require_all=True)
