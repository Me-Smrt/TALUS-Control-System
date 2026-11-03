from __future__ import annotations
import time
from dataclasses import dataclass

from .gpio import GpioZeroOutput
from .manager import CanManager
from .settings import Settings
from .supervisor import SupervisorConfig, SupervisorLink
from . import ccb_protocol as cp


@dataclass
class RuntimeSnapshot:
    supervisor_status: cp.SupervisorStatus | None
    supervisor_hello: cp.SupervisorHello | None
    rcb_interfaces_seen: tuple[str, ...]


class RobotHardwareRuntime:
    """Own the safety-critical Pi hardware communication endpoints.

    The future vision/AI stacks should call into a higher-level command interface rather than
    opening CCB UART or RCB CAN sessions themselves.  Keeping these endpoints owned by one
    control-plane process avoids competing session IDs and makes heartbeat/watchdog behavior
    independent of CV/TTS/STT latency.
    """
    def __init__(self, settings: Settings, interfaces: tuple[str, ...]):
        self.settings = settings
        self._heartbeat_gpio = GpioZeroOutput(settings.supervisor.heartbeat_gpio)
        self.supervisor = SupervisorLink(
            SupervisorConfig(
                serial_device=settings.supervisor.serial_device,
                baudrate=settings.supervisor.baudrate,
                keepalive_period_s=settings.supervisor.keepalive_period_s,
                heartbeat_period_s=settings.supervisor.heartbeat_period_s,
            ),
            heartbeat_write=self._heartbeat_gpio.write,
        )
        self.can = CanManager(list(interfaces))
        self._next_rcb_heartbeat = 0.0
        self._opened = False

    def open(self) -> None:
        if self._opened:
            return
        # Supervisor first: establishes liveness/session and allows the CCB to make channel
        # decisions.  RCB sessions start only after their SocketCAN sockets are open.
        self.supervisor.open()
        for iface in self.can.interfaces.values():
            iface.open()
        self.can.start_sessions()
        self._next_rcb_heartbeat = 0.0
        self._opened = True

    def close(self) -> None:
        if not self._opened:
            self._heartbeat_gpio.close()
            return
        # Best effort only: hardware watchdogs/safety chains still force a safe state if this
        # process dies before these messages can be sent.
        try:
            self.supervisor.disarm()
        except Exception:
            pass
        for iface in self.can.interfaces.values():
            try:
                iface.close()
            except Exception:
                pass
        self.supervisor.close()
        self._heartbeat_gpio.close()
        self._opened = False

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *_exc):
        self.close()

    def enable_can_channels(self, channel_to_interface: dict[int, str]) -> None:
        """Enable CAN transceivers only. This does not enable remote or servo power."""
        for channel in sorted(channel_to_interface):
            result = self.supervisor.set_can_enable_checked(channel, True)
            if result != cp.AckResult.OK:
                raise RuntimeError(f"CCB rejected CAN enable for channel {channel}: {result.name}")

    def service(self, timeout_s: float = 0.0) -> RuntimeSnapshot:
        if not self._opened:
            raise RuntimeError("hardware runtime is not open")
        now = time.monotonic()
        self.supervisor.service_liveness(now)
        if now >= self._next_rcb_heartbeat:
            self.can.send_heartbeats()
            self._next_rcb_heartbeat = now + 0.10
        self.can.poll(timeout_s)
        self.supervisor.drain()
        return RuntimeSnapshot(
            supervisor_status=self.supervisor.last_status,
            supervisor_hello=self.supervisor.last_hello,
            rcb_interfaces_seen=tuple(sorted(self.can.nodes)),
        )
