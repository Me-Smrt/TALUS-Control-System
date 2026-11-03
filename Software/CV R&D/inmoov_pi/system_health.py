from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Any


def _read_pi_temperature_c() -> float | None:
    for path in (Path("/sys/class/thermal/thermal_zone0/temp"), Path("/sys/class/hwmon/hwmon0/temp1_input")):
        try:
            raw = float(path.read_text().strip())
            return raw / 1000.0 if raw > 200.0 else raw
        except Exception:
            continue
    return None


class SystemHealthSampler:
    def __init__(self) -> None:
        self._last_cpu_sample: float | None = None
        try:
            import psutil  # type: ignore
        except Exception:
            psutil = None
        self.psutil = psutil
        if psutil is not None:
            try:
                psutil.cpu_percent(interval=None)
            except Exception:
                pass

    def sample(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "sampled_monotonic_ns": time.monotonic_ns(),
            "cpu_percent": None,
            "memory_percent": None,
            "memory_used_mb": None,
            "disk_percent": None,
            "cpu_temperature_c": _read_pi_temperature_c(),
            "load_1m": None,
            "process_rss_mb": None,
        }
        try:
            result["load_1m"] = float(os.getloadavg()[0])
        except (AttributeError, OSError):
            pass
        try:
            usage = shutil.disk_usage(Path.cwd())
            result["disk_percent"] = 100.0 * usage.used / max(usage.total, 1)
        except Exception:
            pass
        if self.psutil is not None:
            try:
                result["cpu_percent"] = float(self.psutil.cpu_percent(interval=None))
                vm = self.psutil.virtual_memory()
                result["memory_percent"] = float(vm.percent)
                result["memory_used_mb"] = float(vm.used / (1024 * 1024))
                result["process_rss_mb"] = float(self.psutil.Process().memory_info().rss / (1024 * 1024))
            except Exception:
                pass
        return result
