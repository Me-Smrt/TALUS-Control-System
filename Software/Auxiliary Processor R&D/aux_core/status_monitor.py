from __future__ import annotations

import threading
from collections.abc import Callable


class ComponentStatusMonitor:
    """Periodically refresh lightweight auxiliary component status fields.

    Dashboard polling only helps if the state it reads is itself current. This
    monitor prevents startup-only snapshots (LLM/TTS/STT/etc.) from remaining
    stale for the life of the Aux process.
    """

    def __init__(
        self,
        publish: Callable[[str, str], None],
        probes: dict[str, Callable[[], str]],
        *,
        period_s: float = 2.0,
    ) -> None:
        self.publish = publish
        self.probes = dict(probes)
        self.period_s = max(0.5, float(period_s))
        self._last: dict[str, str] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def probe_once(self) -> dict[str, str]:
        current: dict[str, str] = {}
        for name, probe in self.probes.items():
            try:
                status = str(probe())
            except Exception:
                status = "offline"
            current[name] = status
            if self._last.get(name) != status:
                self._last[name] = status
                self.publish(name, status)
        return current

    def _run(self) -> None:
        self.probe_once()
        while not self._stop.wait(self.period_s):
            self.probe_once()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="aux-component-status")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.period_s + 0.5))
            self._thread = None
