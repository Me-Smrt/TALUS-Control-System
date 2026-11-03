from __future__ import annotations

import os
import platform
import shutil
import socket
import time
from pathlib import Path
from typing import Any


def _read_linux_temperature_c() -> float | None:
    """Best-effort CPU/SoC temperature for Jetson/Linux hosts.

    Prefer a CPU/package/SoC thermal zone when Linux exposes names. Fall back
    to the first sane thermal value. Windows development machines normally
    return None, which the dashboard displays as unavailable rather than 0 C.
    """
    thermal_root = Path("/sys/class/thermal")
    if not thermal_root.is_dir():
        return None

    preferred: list[float] = []
    fallback: list[float] = []
    for zone in sorted(thermal_root.glob("thermal_zone*")):
        try:
            raw = float((zone / "temp").read_text().strip())
            value = raw / 1000.0 if abs(raw) > 200.0 else raw
            if not (-20.0 <= value <= 150.0):
                continue
            kind = ""
            try:
                kind = (zone / "type").read_text().strip().lower()
            except Exception:
                pass
            if any(token in kind for token in ("cpu", "soc", "package", "x86_pkg")):
                preferred.append(value)
            fallback.append(value)
        except Exception:
            continue
    values = preferred or fallback
    return values[0] if values else None


class SystemHealthSampler:
    """Low-cost host/process telemetry with graceful stdlib fallbacks."""

    def __init__(self) -> None:
        try:
            import psutil  # type: ignore
        except Exception:
            psutil = None
        self.psutil = psutil
        self.process = None
        if psutil is not None:
            try:
                psutil.cpu_percent(interval=None)
                self.process = psutil.Process()
                self.process.cpu_percent(interval=None)
            except Exception:
                self.process = None

    def sample(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "sampled_monotonic_ns": time.monotonic_ns(),
            "hostname": socket.gethostname(),
            "platform": platform.system(),
            "platform_release": platform.release(),
            "machine": platform.machine(),
            "cpu_count": os.cpu_count(),
            "cpu_percent": None,
            "memory_percent": None,
            "memory_used_mb": None,
            "memory_available_mb": None,
            "memory_total_mb": None,
            "disk_percent": None,
            "disk_used_gb": None,
            "disk_total_gb": None,
            "cpu_temperature_c": _read_linux_temperature_c(),
            "load_1m": None,
            "process_rss_mb": None,
            "process_cpu_percent": None,
        }

        try:
            result["load_1m"] = float(os.getloadavg()[0])
        except (AttributeError, OSError):
            pass

        try:
            usage = shutil.disk_usage(Path.cwd())
            result["disk_percent"] = 100.0 * usage.used / max(usage.total, 1)
            result["disk_used_gb"] = usage.used / (1024**3)
            result["disk_total_gb"] = usage.total / (1024**3)
        except Exception:
            pass

        if self.psutil is not None:
            try:
                result["cpu_percent"] = float(self.psutil.cpu_percent(interval=None))
                vm = self.psutil.virtual_memory()
                result["memory_percent"] = float(vm.percent)
                result["memory_used_mb"] = float(vm.used / (1024**2))
                result["memory_available_mb"] = float(vm.available / (1024**2))
                result["memory_total_mb"] = float(vm.total / (1024**2))
            except Exception:
                pass

        if self.process is not None:
            try:
                result["process_rss_mb"] = float(self.process.memory_info().rss / (1024**2))
                result["process_cpu_percent"] = float(self.process.cpu_percent(interval=None))
            except Exception:
                pass

        return result
