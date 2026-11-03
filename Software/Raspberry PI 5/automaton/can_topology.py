from __future__ import annotations
import re
from pathlib import Path

SPI_DEVICE_RE = re.compile(r"(?:^|/)spi0\.(\d+)(?:/|$)")


class CanTopologyError(RuntimeError):
    pass


def discover_ccb_channels(sys_class_net: Path = Path("/sys/class/net"), expected_channels: int = 8) -> dict[int, str]:
    """Map physical CCB SPI chip-select/channel index -> Linux CAN netdev name.

    Linux netdev numbering is not treated as physical identity.  We derive the CCB channel
    from each CAN device's sysfs SPI path (spi0.<chip-select>) so a canX enumeration change
    cannot silently turn physical channel 2 into channel 5.
    """
    mapping: dict[int, str] = {}
    if not sys_class_net.exists():
        return mapping
    for netdev in sys_class_net.iterdir():
        device = netdev / "device"
        if not device.exists():
            continue
        try:
            resolved = str(device.resolve())
        except OSError:
            continue
        match = SPI_DEVICE_RE.search(resolved)
        if not match:
            continue
        channel = int(match.group(1))
        if not 0 <= channel < expected_channels:
            continue
        if channel in mapping and mapping[channel] != netdev.name:
            raise CanTopologyError(
                f"multiple CAN netdevs resolve to CCB channel {channel}: "
                f"{mapping[channel]} and {netdev.name}"
            )
        mapping[channel] = netdev.name
    return mapping


def ordered_interfaces(mapping: dict[int, str], expected_channels: int = 8, require_all: bool = True) -> tuple[str, ...]:
    missing = [i for i in range(expected_channels) if i not in mapping]
    if require_all and missing:
        raise CanTopologyError("missing physical CCB CAN channels: " + ", ".join(map(str, missing)))
    return tuple(mapping[i] for i in range(expected_channels) if i in mapping)
