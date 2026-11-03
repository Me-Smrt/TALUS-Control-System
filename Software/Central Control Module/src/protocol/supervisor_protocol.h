#pragma once
#include <stdint.h>
#include <stddef.h>

namespace automaton::ccb::protocol {
constexpr size_t FRAME_SIZE = 32;
constexpr size_t PAYLOAD_SIZE = 22;
constexpr uint8_t MAGIC0 = 0xA5;
constexpr uint8_t MAGIC1 = 0x5A;
constexpr uint8_t VERSION = 1;

enum class MessageType : uint8_t {
    SessionBegin = 0x01,
    Keepalive = 0x02,
    StatusRequest = 0x03,
    Disarm = 0x04,
    ArmRequest = 0x05,
    SetRemotePower = 0x06,
    SetCanEnable = 0x07,
    EnterService = 0x08,
    ExitService = 0x09,
    ClearFaults = 0x0A,

    Hello = 0x81,
    Status = 0x82,
    CommandAck = 0x83,
    CurrentTelemetry = 0x84,
    Event = 0x85,
};

enum class AckResult : uint8_t {
    Ok = 0,
    BadProtocol = 1,
    BadCrc = 2,
    BadLength = 3,
    NoSession = 4,
    SessionMismatch = 5,
    InvalidChannel = 6,
    UnsafeState = 7,
    EstopOpen = 8,
    HeartbeatStale = 9,
    UartKeepaliveStale = 10,
    PowerFault = 11,
    PeripheralFault = 12,
    DevOutputLocked = 13,
};

enum class SupervisorState : uint8_t {
    BootSafe = 0,
    SelfTest = 1,
    SafeIdle = 2,
    RunDisarmed = 3,
    RunArmed = 4,
    Fault = 5,
    Estop = 6,
    Service = 7,
};

enum StatusBits : uint16_t {
    STATUS_ESTOP_HEALTHY = 1u << 0,
    STATUS_PI_HEARTBEAT_OK = 1u << 1,
    STATUS_UART_KEEPALIVE_OK = 1u << 2,
    STATUS_PI_BUCK_PG = 1u << 3,
    STATUS_PWR_FAULT_CLEAR = 1u << 4,
    STATUS_CONTROL_IO_OK = 1u << 5,
    STATUS_STATUS_IO_OK = 1u << 6,
    STATUS_ADC_OK = 1u << 7,
    STATUS_SESSION_VALID = 1u << 8,
    STATUS_GLOBAL_ALLOW_ASSERTED = 1u << 9,
    STATUS_SERVICE_ACTIVE = 1u << 10,
};

enum FaultBits : uint32_t {
    FAULT_NONE = 0,
    FAULT_PI_HEARTBEAT_TIMEOUT = 1u << 0,
    FAULT_UART_KEEPALIVE_TIMEOUT = 1u << 1,
    FAULT_PI_POWER = 1u << 2,
    FAULT_PWR_FAULT_N = 1u << 3,
    FAULT_CONTROL_IO = 1u << 4,
    FAULT_STATUS_IO = 1u << 5,
    FAULT_ADC = 1u << 6,
    FAULT_REMOTE_PG_MISMATCH = 1u << 7,
};

struct Frame {
    uint8_t raw[FRAME_SIZE]{};
};

uint16_t crc16Ccitt(const uint8_t* data, size_t len);
uint16_t readU16(const uint8_t* p);
uint32_t readU32(const uint8_t* p);
void writeU16(uint8_t* p, uint16_t v);
void writeU32(uint8_t* p, uint32_t v);

bool decodeFrame(const uint8_t raw[FRAME_SIZE], MessageType& type, uint16_t& seq,
                 const uint8_t*& payload, uint8_t& payload_len);
Frame encodeFrame(MessageType type, uint16_t seq, const uint8_t* payload, uint8_t payload_len);
}
