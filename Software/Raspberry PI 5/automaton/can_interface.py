from __future__ import annotations
import socket, struct
from dataclasses import dataclass
from .protocol import Frame

CAN_FRAME_FMT = "=IB3x8s"
CAN_FRAME_SIZE = struct.calcsize(CAN_FRAME_FMT)
CAN_EFF_FLAG = 0x80000000
CAN_RTR_FLAG = 0x40000000
CAN_ERR_FLAG = 0x20000000
CAN_SFF_MASK = 0x000007FF

@dataclass
class SocketCanInterface:
    name: str
    sock: socket.socket | None = None

    def open(self) -> None:
        if self.sock is not None: return
        s = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
        s.bind((self.name,))
        s.setblocking(False)
        self.sock = s

    def close(self) -> None:
        if self.sock:
            self.sock.close(); self.sock = None

    def fileno(self) -> int:
        if self.sock is None: raise RuntimeError("interface not open")
        return self.sock.fileno()

    def send(self, frame: Frame) -> None:
        if self.sock is None: raise RuntimeError("interface not open")
        raw = struct.pack(CAN_FRAME_FMT, int(frame.can_id) & CAN_SFF_MASK, 8, frame.data)
        self.sock.send(raw)

    def recv(self) -> Frame | None:
        if self.sock is None: raise RuntimeError("interface not open")
        try:
            raw = self.sock.recv(CAN_FRAME_SIZE)
        except BlockingIOError:
            return None
        can_id, dlc, data = struct.unpack(CAN_FRAME_FMT, raw)
        if can_id & (CAN_EFF_FLAG | CAN_RTR_FLAG | CAN_ERR_FLAG): return None
        if dlc != 8: return None
        return Frame(can_id & CAN_SFF_MASK, data[:8])
