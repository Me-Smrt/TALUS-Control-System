from __future__ import annotations
import secrets
import time
from dataclasses import dataclass
from typing import Callable

from . import ccb_protocol as p

@dataclass
class SupervisorConfig:
    serial_device: str = "/dev/serial0"
    baudrate: int = 115200
    keepalive_period_s: float = 0.10
    heartbeat_period_s: float = 0.10

class SupervisorLink:
    """Pi-side CCB Safety Supervisor link.

    Serial I/O uses pyserial when opened. Heartbeat GPIO is deliberately injected as a
    callback so the safety/protocol code is not tied to one Pi GPIO library. On hardware,
    provide a callback that drives BCM GPIO18 / physical pin 12.
    """
    def __init__(self, config: SupervisorConfig | None = None, heartbeat_write: Callable[[bool], None] | None = None):
        self.config = config if config is not None else SupervisorConfig()
        self.heartbeat_write = heartbeat_write
        self.serial = None
        self.session_id = secrets.randbits(32) or 1
        self.seq = 0
        self._heartbeat_level = False
        self._last_keepalive = 0.0
        self._last_heartbeat = 0.0
        self.last_status: p.SupervisorStatus | None = None
        self.last_hello: p.SupervisorHello | None = None
        self._decoder = p.FrameStreamDecoder()
        self._decoded_frames: list[p.Frame] = []

    def open(self) -> None:
        try:
            import serial  # type: ignore
        except ImportError as exc:
            raise RuntimeError("pyserial is required to open the supervisor UART") from exc
        self.serial = serial.Serial(self.config.serial_device, self.config.baudrate, timeout=0.05)
        self.begin_session()

    def begin_session(self) -> int:
        return self.send(p.MessageType.SESSION_BEGIN, p.session_payload(self.session_id))

    def close(self) -> None:
        if self.serial is not None:
            self.serial.close()
            self.serial = None
        if self.heartbeat_write is not None:
            self.heartbeat_write(False)

    def next_seq(self) -> int:
        self.seq = (self.seq + 1) & 0xFFFF
        return self.seq

    def send(self, msg_type: p.MessageType, payload: bytes = b"") -> int:
        if self.serial is None:
            raise RuntimeError("supervisor UART not open")
        seq = self.next_seq()
        self.serial.write(p.encode(p.Frame(msg_type, seq, payload)))
        return seq

    def service_liveness(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        if self.heartbeat_write is not None and now - self._last_heartbeat >= self.config.heartbeat_period_s:
            self._heartbeat_level = not self._heartbeat_level
            self.heartbeat_write(self._heartbeat_level)
            self._last_heartbeat = now
        if self.serial is not None and now - self._last_keepalive >= self.config.keepalive_period_s:
            self.send(p.MessageType.KEEPALIVE, p.session_payload(self.session_id))
            self._last_keepalive = now

    def read_one(self) -> p.Frame | None:
        if self.serial is None:
            raise RuntimeError("supervisor UART not open")
        if not self._decoded_frames and self.serial.in_waiting:
            # Read whatever is currently buffered; FrameStreamDecoder preserves incomplete
            # frames and resynchronizes after corruption or either endpoint resetting.
            chunk = self.serial.read(self.serial.in_waiting)
            self._decoded_frames.extend(self._decoder.feed(chunk))
        if not self._decoded_frames:
            return None
        frame = self._decoded_frames.pop(0)
        if frame.msg_type == p.MessageType.STATUS:
            self.last_status = p.parse_status(frame)
        elif frame.msg_type == p.MessageType.HELLO:
            self.last_hello = p.parse_hello(frame)
        return frame

    def drain(self, limit: int = 64) -> list[p.Frame]:
        frames: list[p.Frame] = []
        for _ in range(limit):
            frame = self.read_one()
            if frame is None:
                break
            frames.append(frame)
        return frames

    def wait_for_ack(self, seq: int, command: p.MessageType, timeout_s: float = 1.0) -> tuple[p.AckResult, int | None]:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            self.service_liveness()
            for frame in self.drain():
                if frame.msg_type != p.MessageType.COMMAND_ACK or frame.seq != seq:
                    continue
                ack_command, result, session, channel = p.parse_ack(frame)
                if ack_command != command:
                    continue
                if command != p.MessageType.SESSION_BEGIN and session not in (0, self.session_id):
                    continue
                return result, channel
            time.sleep(0.002)
        raise TimeoutError(f"Supervisor {command.name} ACK timed out")

    def request_status(self) -> int:
        return self.send(p.MessageType.STATUS_REQUEST)

    def set_can_enable_checked(self, channel: int, enabled: bool, timeout_s: float = 1.0) -> p.AckResult:
        seq = self.set_can_enable(channel, enabled)
        result, _ = self.wait_for_ack(seq, p.MessageType.SET_CAN_ENABLE, timeout_s)
        return result

    def disarm(self) -> int:
        return self.send(p.MessageType.DISARM, p.session_payload(self.session_id))

    def arm(self) -> int:
        return self.send(p.MessageType.ARM_REQUEST, p.session_payload(self.session_id))

    def set_remote_power(self, channel: int, enabled: bool) -> int:
        return self.send(p.MessageType.SET_REMOTE_POWER, p.channel_payload(self.session_id, channel, enabled))

    def set_can_enable(self, channel: int, enabled: bool) -> int:
        return self.send(p.MessageType.SET_CAN_ENABLE, p.channel_payload(self.session_id, channel, enabled))

    def enter_service(self, channel: int) -> int:
        if not 0 <= channel < 8:
            raise ValueError("channel must be 0..7")
        return self.send(p.MessageType.ENTER_SERVICE, self.session_id.to_bytes(4, "little") + bytes([channel]))

    def exit_service(self) -> int:
        return self.send(p.MessageType.EXIT_SERVICE, p.session_payload(self.session_id))

    def clear_faults(self, mask: int) -> int:
        return self.send(p.MessageType.CLEAR_FAULTS, p.clear_faults_payload(self.session_id, mask))
