from __future__ import annotations
from dataclasses import dataclass
from enum import IntEnum, IntFlag
import struct

FRAME_SIZE = 32
PAYLOAD_SIZE = 22
MAGIC = b"\xA5\x5A"
VERSION = 1

class MessageType(IntEnum):
    SESSION_BEGIN = 0x01
    KEEPALIVE = 0x02
    STATUS_REQUEST = 0x03
    DISARM = 0x04
    ARM_REQUEST = 0x05
    SET_REMOTE_POWER = 0x06
    SET_CAN_ENABLE = 0x07
    ENTER_SERVICE = 0x08
    EXIT_SERVICE = 0x09
    CLEAR_FAULTS = 0x0A
    HELLO = 0x81
    STATUS = 0x82
    COMMAND_ACK = 0x83
    CURRENT_TELEMETRY = 0x84
    EVENT = 0x85

class AckResult(IntEnum):
    OK = 0
    BAD_PROTOCOL = 1
    BAD_CRC = 2
    BAD_LENGTH = 3
    NO_SESSION = 4
    SESSION_MISMATCH = 5
    INVALID_CHANNEL = 6
    UNSAFE_STATE = 7
    ESTOP_OPEN = 8
    HEARTBEAT_STALE = 9
    UART_KEEPALIVE_STALE = 10
    POWER_FAULT = 11
    PERIPHERAL_FAULT = 12
    DEV_OUTPUT_LOCKED = 13

class SupervisorState(IntEnum):
    BOOT_SAFE = 0
    SELF_TEST = 1
    SAFE_IDLE = 2
    RUN_DISARMED = 3
    RUN_ARMED = 4
    FAULT = 5
    ESTOP = 6
    SERVICE = 7

class StatusBits(IntFlag):
    ESTOP_HEALTHY = 1 << 0
    PI_HEARTBEAT_OK = 1 << 1
    UART_KEEPALIVE_OK = 1 << 2
    PI_BUCK_PG = 1 << 3
    PWR_FAULT_CLEAR = 1 << 4
    CONTROL_IO_OK = 1 << 5
    STATUS_IO_OK = 1 << 6
    ADC_OK = 1 << 7
    SESSION_VALID = 1 << 8
    GLOBAL_ALLOW_ASSERTED = 1 << 9
    SERVICE_ACTIVE = 1 << 10

class FaultBits(IntFlag):
    NONE = 0
    PI_HEARTBEAT_TIMEOUT = 1 << 0
    UART_KEEPALIVE_TIMEOUT = 1 << 1
    PI_POWER = 1 << 2
    PWR_FAULT_N = 1 << 3
    CONTROL_IO = 1 << 4
    STATUS_IO = 1 << 5
    ADC = 1 << 6
    REMOTE_PG_MISMATCH = 1 << 7

@dataclass(frozen=True)
class Frame:
    msg_type: MessageType
    seq: int
    payload: bytes = b""

@dataclass(frozen=True)
class SupervisorStatus:
    state: SupervisorState
    status: StatusBits
    faults: FaultBits
    remote_enable_mask: int
    remote_pg_mask: int
    can_enable_mask: int
    current_valid_mask: int
    service_channel: int | None
    session_id: int
    heartbeat_age_ms: int
    uart_age_ms: int

@dataclass(frozen=True)
class SupervisorHello:
    protocol_version: int
    hardware_revision: int
    firmware: tuple[int, int, int]
    control_io_addr: int
    status_io_addr: int
    adc_addr: int
    channel_count: int


def crc16_ccitt(data: bytes) -> int:
    crc = 0xFFFF
    for value in data:
        crc ^= value << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def encode(frame: Frame) -> bytes:
    if len(frame.payload) > PAYLOAD_SIZE:
        raise ValueError(f"payload too large: {len(frame.payload)} > {PAYLOAD_SIZE}")
    raw = bytearray(FRAME_SIZE)
    raw[0:2] = MAGIC
    raw[2] = VERSION
    raw[3] = int(frame.msg_type)
    struct.pack_into("<H", raw, 4, frame.seq & 0xFFFF)
    raw[6] = len(frame.payload)
    raw[7] = 0
    raw[8:8 + len(frame.payload)] = frame.payload
    struct.pack_into("<H", raw, 30, crc16_ccitt(bytes(raw[:30])))
    return bytes(raw)


def decode(raw: bytes) -> Frame:
    if len(raw) != FRAME_SIZE:
        raise ValueError(f"frame must be {FRAME_SIZE} bytes")
    if raw[:2] != MAGIC:
        raise ValueError("bad supervisor frame magic")
    if raw[2] != VERSION:
        raise ValueError(f"supervisor protocol mismatch: {raw[2]}")
    length = raw[6]
    if length > PAYLOAD_SIZE:
        raise ValueError("invalid payload length")
    expected = struct.unpack_from("<H", raw, 30)[0]
    actual = crc16_ccitt(raw[:30])
    if expected != actual:
        raise ValueError("bad supervisor frame CRC")
    return Frame(MessageType(raw[3]), struct.unpack_from("<H", raw, 4)[0], bytes(raw[8:8 + length]))


def session_payload(session_id: int) -> bytes:
    return struct.pack("<I", session_id)

def channel_payload(session_id: int, channel: int, enabled: bool) -> bytes:
    if not 0 <= channel < 8:
        raise ValueError("channel must be 0..7")
    return struct.pack("<IBB", session_id, channel, int(enabled))

def clear_faults_payload(session_id: int, mask: int) -> bytes:
    return struct.pack("<II", session_id, mask)


def parse_hello(frame: Frame) -> SupervisorHello:
    if frame.msg_type != MessageType.HELLO or len(frame.payload) < 9:
        raise ValueError("not a valid HELLO")
    pv, hw, ma, mi, pa, control, status, adc, channels = struct.unpack_from("<BBBBBBBBB", frame.payload)
    return SupervisorHello(pv, hw, (ma, mi, pa), control, status, adc, channels)


def parse_status(frame: Frame) -> SupervisorStatus:
    if frame.msg_type != MessageType.STATUS or len(frame.payload) < 20:
        raise ValueError("not a valid STATUS")
    state = SupervisorState(frame.payload[0])
    status = StatusBits(struct.unpack_from("<H", frame.payload, 1)[0])
    faults = FaultBits(struct.unpack_from("<I", frame.payload, 3)[0])
    service = frame.payload[11]
    return SupervisorStatus(
        state=state,
        status=status,
        faults=faults,
        remote_enable_mask=frame.payload[7],
        remote_pg_mask=frame.payload[8],
        can_enable_mask=frame.payload[9],
        current_valid_mask=frame.payload[10],
        service_channel=None if service == 0xFF else service,
        session_id=struct.unpack_from("<I", frame.payload, 12)[0],
        heartbeat_age_ms=struct.unpack_from("<H", frame.payload, 16)[0],
        uart_age_ms=struct.unpack_from("<H", frame.payload, 18)[0],
    )


def parse_ack(frame: Frame) -> tuple[MessageType, AckResult, int, int | None]:
    if frame.msg_type != MessageType.COMMAND_ACK or len(frame.payload) < 7:
        raise ValueError("not a valid COMMAND_ACK")
    command = MessageType(frame.payload[0])
    result = AckResult(frame.payload[1])
    session = struct.unpack_from("<I", frame.payload, 2)[0]
    channel = frame.payload[6]
    return command, result, session, None if channel == 0xFF else channel


class FrameStreamDecoder:
    """Resynchronizing decoder for the fixed-size Supervisor UART frames.

    UART byte streams can begin mid-frame after either endpoint resets or can contain a
    damaged frame.  The decoder searches for the two-byte magic, validates version/CRC,
    and advances one byte on a bad candidate rather than permanently losing alignment.
    """
    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, data: bytes) -> list[Frame]:
        if data:
            self._buffer.extend(data)
        frames: list[Frame] = []
        while True:
            idx = self._buffer.find(MAGIC)
            if idx < 0:
                # Preserve a trailing first magic byte so a split magic sequence survives.
                if self._buffer[-1:] == MAGIC[:1]:
                    self._buffer[:] = self._buffer[-1:]
                else:
                    self._buffer.clear()
                break
            if idx:
                del self._buffer[:idx]
            if len(self._buffer) < FRAME_SIZE:
                break
            candidate = bytes(self._buffer[:FRAME_SIZE])
            try:
                frame = decode(candidate)
            except (ValueError, KeyError):
                del self._buffer[0]
                continue
            frames.append(frame)
            del self._buffer[:FRAME_SIZE]
        return frames
