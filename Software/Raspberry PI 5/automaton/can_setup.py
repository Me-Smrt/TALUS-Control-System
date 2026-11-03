from __future__ import annotations
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from .can_timing import require_supported_bitrate

Runner = Callable[..., subprocess.CompletedProcess]

@dataclass(frozen=True)
class CanInterfaceState:
    name: str
    exists: bool
    operstate: str | None = None


def interface_exists(name: str, sys_class_net: Path = Path("/sys/class/net")) -> bool:
    return (sys_class_net / name).exists()


def list_states(names: Iterable[str], sys_class_net: Path = Path("/sys/class/net")) -> list[CanInterfaceState]:
    out: list[CanInterfaceState] = []
    for name in names:
        base = sys_class_net / name
        if not base.exists():
            out.append(CanInterfaceState(name, False, None))
            continue
        try:
            state = (base / "operstate").read_text().strip()
        except OSError:
            state = None
        out.append(CanInterfaceState(name, True, state))
    return out


def _run(args: list[str], runner: Runner = subprocess.run) -> subprocess.CompletedProcess:
    return runner(args, check=True, text=True, capture_output=True)


def configure_interface(name: str, bitrate: int, restart_ms: int = 100, runner: Runner = subprocess.run) -> None:
    require_supported_bitrate(bitrate)
    _run(["ip", "link", "set", "dev", name, "down"], runner)
    _run([
        "ip", "link", "set", "dev", name, "type", "can",
        "bitrate", str(bitrate), "restart-ms", str(restart_ms),
    ], runner)
    _run(["ip", "link", "set", "dev", name, "up"], runner)


def configure_all(names: Iterable[str], bitrate: int, restart_ms: int = 100,
                  runner: Runner = subprocess.run, require_all: bool = True,
                  sys_class_net: Path = Path("/sys/class/net")) -> list[str]:
    configured: list[str] = []
    missing: list[str] = []
    for name in names:
        if not interface_exists(name, sys_class_net):
            missing.append(name)
            continue
        configure_interface(name, bitrate, restart_ms, runner)
        configured.append(name)
    if require_all and missing:
        raise RuntimeError(f"missing SocketCAN interfaces: {', '.join(missing)}")
    return configured


def read_link_details(name: str, runner: Runner = subprocess.run) -> dict:
    result = _run(["ip", "-details", "-json", "link", "show", "dev", name], runner)
    values = json.loads(result.stdout)
    if not values:
        raise RuntimeError(f"no ip-link data for {name}")
    return values[0]
