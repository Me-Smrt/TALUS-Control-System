from __future__ import annotations
import logging, secrets, select, time
from dataclasses import dataclass
from .can_interface import SocketCanInterface
from .protocol import *

log = logging.getLogger("automaton.manager")

@dataclass
class DetectedNode:
    interface: str
    hello: HelloRecord
    last_seen: float

class CanManager:
    def __init__(self, interface_names: list[str]):
        self.interfaces = {name: SocketCanInterface(name) for name in interface_names}
        self.assemblers = {name: HelloAssembler() for name in interface_names}
        self.nodes: dict[str, DetectedNode] = {}
        self.session_id = secrets.randbits(32) or 1
        self.seq = 0

    def __enter__(self):
        for iface in self.interfaces.values(): iface.open()
        return self

    def __exit__(self, *exc):
        for iface in self.interfaces.values(): iface.close()

    def next_seq(self) -> int:
        self.seq = (self.seq + 1) & 0xFFFF
        return self.seq

    def start_sessions(self) -> None:
        for iface in self.interfaces.values():
            iface.send(session_begin(self.session_id, self.next_seq()))

    def send_heartbeats(self) -> None:
        for iface in self.interfaces.values():
            iface.send(heartbeat(self.session_id, self.next_seq()))

    def poll(self, timeout: float = 0.1) -> list[tuple[str, Frame]]:
        socks = [i.sock for i in self.interfaces.values() if i.sock]
        if not socks: return []
        readable, _, _ = select.select(socks, [], [], timeout)
        by_fd = {i.fileno(): name for name, i in self.interfaces.items() if i.sock}
        out = []
        for sock in readable:
            name = by_fd[sock.fileno()]
            while True:
                frame = self.interfaces[name].recv()
                if frame is None: break
                out.append((name, frame))
                hello = self.assemblers[name].feed(frame)
                if hello:
                    self.nodes[name] = DetectedNode(name, hello, time.monotonic())
                    log.info("rcb_hello", extra={"interface": name, "uid": f"{hello.uid:016X}", "role": hello.role.name})
        return out

    def discover(self, duration: float = 2.0) -> dict[str, DetectedNode]:
        self.start_sessions()
        deadline = time.monotonic() + duration
        next_hb = 0.0
        while time.monotonic() < deadline:
            now = time.monotonic()
            if now >= next_hb:
                self.send_heartbeats(); next_hb = now + 0.1
            self.poll(min(0.1, max(0.0, deadline - now)))
        return dict(self.nodes)

    def wait_for_identify(self, timeout: float = 30.0) -> tuple[str, int]:
        deadline = time.monotonic() + timeout
        next_hb = 0.0
        while time.monotonic() < deadline:
            now = time.monotonic()
            if now >= next_hb:
                self.send_heartbeats(); next_hb = now + 0.1
            for iface, frame in self.poll(0.1):
                if frame.can_id == CanId.IDENTIFY_EVENT:
                    return iface, parse_identify(frame)
        raise TimeoutError("no IDENTIFY event received")

    def set_role(self, interface: str, role: Role, timeout: float = 2.0) -> AckResult:
        seq = self.next_seq()
        self.interfaces[interface].send(set_role(self.session_id, role, seq))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for iface, frame in self.poll(0.1):
                if iface == interface and frame.can_id == CanId.CONFIG_ACK:
                    result, session, ack_seq = parse_ack(frame)
                    if session == self.session_id and ack_seq == seq: return result
        raise TimeoutError("SET_ROLE acknowledgement timed out")

    def disarm(self, interface: str, reason: int = 0) -> None:
        self.interfaces[interface].send(disarm(self.session_id, self.next_seq(), reason))

    def request_arm(self, interface: str, timeout: float = 2.0) -> AckResult:
        seq = self.next_seq()
        self.interfaces[interface].send(arm_request(self.session_id, seq))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for iface, frame in self.poll(0.1):
                if iface == interface and frame.can_id == CanId.ARM_ACK:
                    result, session, ack_seq = parse_ack(frame)
                    if session == self.session_id and ack_seq == seq:
                        return result
        raise TimeoutError("ARM acknowledgement timed out")

    def command_servo(self, interface: str, channel: int, position_permille: int) -> None:
        self.interfaces[interface].send(servo_command(self.session_id, channel, position_permille))
