from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import tomllib

from .can_timing import require_supported_bitrate

DEFAULT_CONFIG_PATH = Path("/etc/automaton/automaton.toml")

@dataclass(frozen=True)
class CanSettings:
    bitrate: int = 500_000
    restart_ms: int = 100
    interfaces: tuple[str, ...] = tuple(f"can{i}" for i in range(8))
    auto_discover_by_spi: bool = True

@dataclass(frozen=True)
class SupervisorSettings:
    serial_device: str = "/dev/serial0"
    baudrate: int = 115200
    heartbeat_gpio: int = 18
    heartbeat_period_s: float = 0.10
    keepalive_period_s: float = 0.10

@dataclass(frozen=True)
class PathSettings:
    registry: Path = Path("/var/lib/automaton/rcb_registry.json")
    log_directory: Path = Path("/var/log/automaton")

@dataclass(frozen=True)
class Settings:
    can: CanSettings = field(default_factory=CanSettings)
    supervisor: SupervisorSettings = field(default_factory=SupervisorSettings)
    paths: PathSettings = field(default_factory=PathSettings)


def load_settings(path: Path | str = DEFAULT_CONFIG_PATH) -> Settings:
    path = Path(path)
    if not path.exists():
        return Settings()
    with path.open("rb") as fh:
        raw = tomllib.load(fh)

    can_raw = raw.get("can", {})
    bitrate = int(can_raw.get("bitrate", 500_000))
    require_supported_bitrate(bitrate)
    restart_ms = int(can_raw.get("restart_ms", 100))
    interfaces = tuple(str(x) for x in can_raw.get("interfaces", [f"can{i}" for i in range(8)]))
    if not interfaces:
        raise ValueError("at least one CAN interface is required")
    auto_discover_by_spi = bool(can_raw.get("auto_discover_by_spi", True))

    sup_raw = raw.get("supervisor", {})
    supervisor = SupervisorSettings(
        serial_device=str(sup_raw.get("serial_device", "/dev/serial0")),
        baudrate=int(sup_raw.get("baudrate", 115200)),
        heartbeat_gpio=int(sup_raw.get("heartbeat_gpio", 18)),
        heartbeat_period_s=float(sup_raw.get("heartbeat_period_s", 0.10)),
        keepalive_period_s=float(sup_raw.get("keepalive_period_s", 0.10)),
    )

    paths_raw = raw.get("paths", {})
    paths = PathSettings(
        registry=Path(paths_raw.get("registry", "/var/lib/automaton/rcb_registry.json")),
        log_directory=Path(paths_raw.get("log_directory", "/var/log/automaton")),
    )
    return Settings(CanSettings(bitrate, restart_ms, interfaces, auto_discover_by_spi), supervisor, paths)
