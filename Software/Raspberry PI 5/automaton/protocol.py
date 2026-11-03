from __future__ import annotations
from dataclasses import dataclass
from enum import IntEnum, IntFlag
import struct

PROTOCOL_VERSION = 1

class CanId(IntEnum):
    DISARM = 0x080
    HEARTBEAT = 0x100
    SESSION_BEGIN = 0x110
    ARM_REQUEST = 0x120
    SET_ROLE = 0x130
    PING = 0x140
    SERVO_COMMAND = 0x150
    HELLO_UID = 0x200
    HELLO_META = 0x201
    HELLO_CAPS = 0x202
    HELLO_STATE = 0x203
    STATUS = 0x210
    ARM_ACK = 0x220
    IDENTIFY_EVENT = 0x230
    CONFIG_ACK = 0x240
    PONG = 0x250

class RcbState(IntEnum):
    RESET = 0
    SAFE_BOOT = 1
    USB_ONLY = 2
    INITIALIZING = 3
    READY_DISARMED = 4
    ARMED = 5
    FAULT_LOCKOUT = 6
    SERVICE = 7
    ARMING_WAIT_POWER_GOOD = 8

class Role(IntEnum):
    UNASSIGNED = 0
    HEAD = 1
    LEFT_ARM = 2
    RIGHT_ARM = 3
    TORSO = 4
    LEFT_HAND = 5
    RIGHT_HAND = 6
    LEFT_LEG = 7
    RIGHT_LEG = 8
    CUSTOM = 0x7F

class StatusBits(IntFlag):
    LOGIC_POWER_OK = 1 << 0
    CAN_OK = 1 << 1
    GLOBAL_ALLOW = 1 << 2
    LOCAL_ENABLE = 1 << 3
    SERVO_MASTER = 1 << 4
    BANK_A_PG = 1 << 5
    BANK_B_PG = 1 << 6
    BANK_C_PG = 1 << 7
    BANK_D_PG = 1 << 8
    PCA0_PRESENT = 1 << 9
    PCA1_PRESENT = 1 << 10
    PAIRED = 1 << 11
    SESSION_VALID = 1 << 12
    ARMED = 1 << 13
    ARMING = 1 << 14

class FaultBits(IntFlag):
    NONE = 0
    CAN_TIMEOUT = 1 << 0
    LOGIC_POWER = 1 << 1
    PCA0_MISSING = 1 << 2
    PCA1_MISSING = 1 << 3
    BANK_A_PG = 1 << 4
    BANK_B_PG = 1 << 5
    BANK_C_PG = 1 << 6
    BANK_D_PG = 1 << 7
    GLOBAL_ALLOW_LOST = 1 << 8
    WATCHDOG_RESET = 1 << 9
    CONFIG = 1 << 10
    ROLE_CONFLICT = 1 << 11
    CAN_CONTROLLER = 1 << 12

class AckResult(IntEnum):
    OK = 0
    BAD_PROTOCOL = 1
    NO_SESSION = 2
    SESSION_MISMATCH = 3
    LOGIC_POWER_MISSING = 4
    GLOBAL_ALLOW_MISSING = 5
    CAN_STALE = 6
    PCA_MISSING = 7
    BANK_POWER_GOOD_MISSING = 8
    CONFIG_INVALID = 9
    FAULT_ACTIVE = 10
    DEV_OUTPUT_LOCKED = 11
    INVALID_ROLE = 12
    ARM_PENDING = 13

@dataclass(frozen=True)
class Frame:
    can_id: int
    data: bytes
    def __post_init__(self):
        if len(self.data) != 8:
            raise ValueError("Automaton protocol v1 uses fixed 8-byte classic CAN payloads")

@dataclass
class HelloRecord:
    uid: int
    role: Role
    protocol_version: int
    hardware_revision: int
    config_version: int
    firmware: tuple[int, int, int]
    reset_reason: int
    pwm_channel_count: int
    bank_count: int
    supported_bank_mask: int
    feature_flags: int
    state: RcbState
    status: StatusBits
    faults: FaultBits


def session_begin(session: int, seq: int = 0, flags: int = 0) -> Frame:
    return Frame(CanId.SESSION_BEGIN, struct.pack("<BIHB", PROTOCOL_VERSION, session, seq, flags))

def heartbeat(session: int, seq: int, flags: int = 0) -> Frame:
    return Frame(CanId.HEARTBEAT, struct.pack("<BIHB", PROTOCOL_VERSION, session, seq, flags))

def arm_request(session: int, seq: int, flags: int = 0) -> Frame:
    return Frame(CanId.ARM_REQUEST, struct.pack("<BIHB", PROTOCOL_VERSION, session, seq, flags))

def disarm(session: int, seq: int, reason: int = 0) -> Frame:
    return Frame(CanId.DISARM, struct.pack("<BBIH", PROTOCOL_VERSION, reason, session, seq))

def set_role(session: int, role: Role, seq: int) -> Frame:
    return Frame(CanId.SET_ROLE, struct.pack("<BIBH", PROTOCOL_VERSION, session, int(role), seq))

def ping(session: int, nonce: int, flags: int = 0) -> Frame:
    return Frame(CanId.PING, struct.pack("<BIHB", PROTOCOL_VERSION, session, nonce, flags))

def servo_command(session: int, channel: int, position_permille: int) -> Frame:
    if not 0 <= channel < 32:
        raise ValueError("servo channel must be 0..31")
    if not -1000 <= position_permille <= 1000:
        raise ValueError("position_permille must be within -1000..1000")
    return Frame(CanId.SERVO_COMMAND, struct.pack("<BIBh", PROTOCOL_VERSION, session, channel, position_permille))

def parse_identify(frame: Frame) -> int:
    if frame.can_id != CanId.IDENTIFY_EVENT: raise ValueError("not IDENTIFY_EVENT")
    return struct.unpack("<Q", frame.data)[0]

def parse_status(frame: Frame):
    if frame.can_id != CanId.STATUS: raise ValueError("not STATUS")
    state, role, status, faults = struct.unpack("<BBHI", frame.data)
    return RcbState(state), Role(role), StatusBits(status), FaultBits(faults)

def parse_ack(frame: Frame) -> tuple[AckResult, int, int]:
    if frame.can_id not in (CanId.ARM_ACK, CanId.CONFIG_ACK): raise ValueError("not ACK")
    version, result, session, seq = struct.unpack("<BBIH", frame.data)
    if version != PROTOCOL_VERSION: raise ValueError(f"protocol mismatch {version}")
    return AckResult(result), session, seq

class HelloAssembler:
    """Assembles the four HELLO frames independently for one SocketCAN interface."""
    def __init__(self):
        self.parts: dict[int, bytes] = {}

    def feed(self, frame: Frame) -> HelloRecord | None:
        if frame.can_id not in (CanId.HELLO_UID, CanId.HELLO_META, CanId.HELLO_CAPS, CanId.HELLO_STATE):
            return None
        self.parts[int(frame.can_id)] = frame.data
        required = [int(CanId.HELLO_UID), int(CanId.HELLO_META), int(CanId.HELLO_CAPS), int(CanId.HELLO_STATE)]
        if not all(k in self.parts for k in required): return None

        uid = struct.unpack("<Q", self.parts[int(CanId.HELLO_UID)])[0]
        pv, role, hw, cv, ma, mi, pa, reset = struct.unpack("<BBBBBBBB", self.parts[int(CanId.HELLO_META)])
        pwm, banks, mask, feature, _, _, _ = struct.unpack("<BBB H BBB", self.parts[int(CanId.HELLO_CAPS)])
        state, status, faults, _ = struct.unpack("<BHI B", self.parts[int(CanId.HELLO_STATE)])
        self.parts.clear()
        return HelloRecord(
            uid=uid, role=Role(role), protocol_version=pv, hardware_revision=hw,
            config_version=cv, firmware=(ma, mi, pa), reset_reason=reset,
            pwm_channel_count=pwm, bank_count=banks, supported_bank_mask=mask,
            feature_flags=feature, state=RcbState(state), status=StatusBits(status), faults=FaultBits(faults),
        )
