#pragma once
#include <stdint.h>

namespace automaton::protocol {

enum class CanId : uint16_t {
    Disarm       = 0x080,
    Heartbeat    = 0x100,
    SessionBegin = 0x110,
    ArmRequest   = 0x120,
    SetRole      = 0x130,
    Ping         = 0x140,
    ServoCommand = 0x150,

    HelloUid     = 0x200,
    HelloMeta    = 0x201,
    HelloCaps    = 0x202,
    HelloState   = 0x203,
    Status       = 0x210,
    ArmAck       = 0x220,
    Identify     = 0x230,
    ConfigAck    = 0x240,
    Pong         = 0x250,
};

enum class RcbState : uint8_t {
    Reset = 0,
    SafeBoot = 1,
    UsbOnly = 2,
    Initializing = 3,
    ReadyDisarmed = 4,
    Armed = 5,
    FaultLockout = 6,
    Service = 7,
    ArmingWaitPowerGood = 8,
};

enum class Role : uint8_t {
    Unassigned = 0,
    Head = 1,
    LeftArm = 2,
    RightArm = 3,
    Torso = 4,
    LeftHand = 5,
    RightHand = 6,
    LeftLeg = 7,
    RightLeg = 8,
    Custom = 0x7F,
};

enum StatusBits : uint16_t {
    STATUS_LOGIC_POWER_OK   = 1u << 0,
    STATUS_CAN_OK           = 1u << 1,
    STATUS_GLOBAL_ALLOW     = 1u << 2,
    STATUS_LOCAL_ENABLE     = 1u << 3,
    STATUS_SERVO_MASTER     = 1u << 4,
    STATUS_BANK_A_PG        = 1u << 5,
    STATUS_BANK_B_PG        = 1u << 6,
    STATUS_BANK_C_PG        = 1u << 7,
    STATUS_BANK_D_PG        = 1u << 8,
    STATUS_PCA0_PRESENT     = 1u << 9,
    STATUS_PCA1_PRESENT     = 1u << 10,
    STATUS_PAIRED           = 1u << 11,
    STATUS_SESSION_VALID    = 1u << 12,
    STATUS_ARMED            = 1u << 13,
    STATUS_ARMING           = 1u << 14,
};

enum FaultBits : uint32_t {
    FAULT_NONE              = 0,
    FAULT_CAN_TIMEOUT       = 1ul << 0,
    FAULT_LOGIC_POWER       = 1ul << 1,
    FAULT_PCA0_MISSING      = 1ul << 2,
    FAULT_PCA1_MISSING      = 1ul << 3,
    FAULT_BANK_A_PG         = 1ul << 4,
    FAULT_BANK_B_PG         = 1ul << 5,
    FAULT_BANK_C_PG         = 1ul << 6,
    FAULT_BANK_D_PG         = 1ul << 7,
    FAULT_GLOBAL_ALLOW_LOST = 1ul << 8,
    FAULT_WATCHDOG_RESET    = 1ul << 9,
    FAULT_CONFIG            = 1ul << 10,
    FAULT_ROLE_CONFLICT     = 1ul << 11,
    FAULT_CAN_CONTROLLER    = 1ul << 12,
};

enum class AckResult : uint8_t {
    Ok = 0,
    BadProtocol = 1,
    NoSession = 2,
    SessionMismatch = 3,
    LogicPowerMissing = 4,
    GlobalAllowMissing = 5,
    CanStale = 6,
    PcaMissing = 7,
    BankPowerGoodMissing = 8,
    ConfigInvalid = 9,
    FaultActive = 10,
    DevOutputLocked = 11,
    InvalidRole = 12,
    ArmPending = 13,
};

enum class DisarmReason : uint8_t {
    HostRequest = 0,
    HeartbeatTimeout = 1,
    GlobalAllowLost = 2,
    LogicPowerLost = 3,
    Fault = 4,
    NewSession = 5,
    PeripheralLost = 6,
    BankPowerGoodLost = 7,
};

struct CanFrame {
    uint16_t id = 0;
    uint8_t dlc = 8;
    uint8_t data[8] = {0};
};

struct Capabilities {
    uint8_t pwm_channel_count = 32;
    uint8_t bank_count = 4;
    uint8_t supported_bank_mask = 0x0F;
    uint16_t feature_flags = 0;
};

}  // namespace automaton::protocol
