from __future__ import annotations

import json
import socket
from typing import Any

from .util import as_builtin


class UdpJsonPublisher:
    def __init__(self, host: str = "127.0.0.1", port: int = 8765, max_bytes: int = 60000) -> None:
        self.address = (host, int(port))
        self.max_bytes = int(max_bytes)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send(self, payload: dict[str, Any]) -> int:
        encoded = json.dumps(as_builtin(payload), separators=(",", ":"), allow_nan=False).encode("utf-8")
        if len(encoded) > self.max_bytes:
            raise ValueError(f"Bridge datagram is {len(encoded)} bytes; limit is {self.max_bytes}")
        return self.sock.sendto(encoded, self.address)

    def close(self) -> None:
        self.sock.close()
