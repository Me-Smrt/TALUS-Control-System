#include <Arduino.h>
#include <Wire.h>
#include "board/pins.h"
#include "board/board_config.h"
#include "drivers/tca9535.h"
#include "drivers/ads7138.h"
#include "protocol/supervisor_protocol.h"
#include "safety/safety_manager.h"

using namespace automaton::ccb;

drivers::Tca9535 control_io(Wire, board::TCA_CONTROL_ADDR);
drivers::Tca9535 status_io(Wire, board::TCA_STATUS_ADDR);
drivers::Ads7138 current_adc(Wire, board::ADS7138_ADDR);
safety::SafetyManager safety_manager;

static bool control_io_ok = false;
static bool status_io_ok = false;
static bool adc_ok = false;
static uint8_t remote_enable_mask = 0;
static uint8_t can_enable_mask = 0;
static uint8_t remote_pg_mask = 0;
static uint32_t active_session = 0;
static uint32_t last_uart_keepalive_ms = 0;
static bool uart_keepalive_seen = false;
static uint32_t last_pi_hb_edge_ms = 0;
static bool pi_hb_edge_seen = false;
static int last_pi_hb_level = LOW;
static uint32_t last_status_ms = 0;
static uint32_t last_hello_ms = 0;
static uint16_t tx_seq = 0;

static uint8_t uart_rx[protocol::FRAME_SIZE]{};
static size_t uart_rx_used = 0;

static bool validSession(const uint8_t* payload, uint8_t len) {
    return len >= 4 && active_session != 0 && protocol::readU32(payload) == active_session;
}

static void sendFrame(protocol::MessageType type, uint16_t seq, const uint8_t* payload, uint8_t len) {
    const auto f = protocol::encodeFrame(type, seq, payload, len);
    Serial1.write(f.raw, protocol::FRAME_SIZE);
}

static void sendAck(protocol::MessageType command, protocol::AckResult result, uint16_t seq, uint8_t channel = 0xFF) {
    uint8_t p[8]{};
    p[0] = uint8_t(command); p[1] = uint8_t(result);
    protocol::writeU32(&p[2], active_session);
    p[6] = channel;
    sendFrame(protocol::MessageType::CommandAck, seq, p, 7);
}

static uint16_t heartbeatAge(uint32_t now) {
    if (!pi_hb_edge_seen) return 0xFFFF;
    const uint32_t age = now - last_pi_hb_edge_ms;
    return age > 0xFFFF ? 0xFFFF : uint16_t(age);
}
static uint16_t uartAge(uint32_t now) {
    if (!uart_keepalive_seen) return 0xFFFF;
    const uint32_t age = now - last_uart_keepalive_ms;
    return age > 0xFFFF ? 0xFFFF : uint16_t(age);
}

static void sendHello() {
    uint8_t p[12]{};
    p[0] = board::SUPERVISOR_PROTOCOL_VERSION;
    p[1] = board::HARDWARE_REVISION;
    p[2] = board::FW_MAJOR; p[3] = board::FW_MINOR; p[4] = board::FW_PATCH;
    p[5] = board::TCA_CONTROL_ADDR; p[6] = board::TCA_STATUS_ADDR; p[7] = board::ADS7138_ADDR;
    p[8] = 8; // remote channel count
    sendFrame(protocol::MessageType::Hello, ++tx_seq, p, 9);
}

static void sendStatus(uint32_t now) {
    uint8_t p[22]{};
    p[0] = uint8_t(safety_manager.state());
    protocol::writeU16(&p[1], safety_manager.statusBits());
    protocol::writeU32(&p[3], safety_manager.faults());
    p[7] = remote_enable_mask;
    p[8] = remote_pg_mask;
    p[9] = can_enable_mask;
    p[10] = 0; // current-valid mask; ADS conversion stage not implemented yet.
    p[11] = safety_manager.serviceChannel() < 0 ? 0xFF : uint8_t(safety_manager.serviceChannel());
    protocol::writeU32(&p[12], active_session);
    protocol::writeU16(&p[16], heartbeatAge(now));
    protocol::writeU16(&p[18], uartAge(now));
    sendFrame(protocol::MessageType::Status, ++tx_seq, p, 20);
}

static bool setRemotePower(uint8_t channel, bool enabled) {
    if (channel >= 8 || !control_io_ok) return false;
#if AUTOMATON_CCB_REMOTE_POWER_OUTPUTS_ENABLED
    if (enabled) remote_enable_mask |= uint8_t(1u << channel);
    else remote_enable_mask &= uint8_t(~(1u << channel));
#else
    remote_enable_mask = 0;
    if (enabled) return false;
#endif
    return control_io.setPort0(remote_enable_mask);
}

static bool setCanEnable(uint8_t channel, bool enabled) {
    if (channel >= 8 || !status_io_ok) return false;
#if AUTOMATON_CCB_CAN_CHANNEL_ENABLE_OUTPUTS_ENABLED
    if (enabled) can_enable_mask |= uint8_t(1u << channel);
    else can_enable_mask &= uint8_t(~(1u << channel));
#else
    can_enable_mask = 0;
    if (enabled) return false;
#endif
    return status_io.setPort0(can_enable_mask);
}

static void handleCommand(protocol::MessageType type, uint16_t seq, const uint8_t* p, uint8_t len, uint32_t now) {
    switch (type) {
        case protocol::MessageType::SessionBegin: {
            if (len < 4) { sendAck(type, protocol::AckResult::BadLength, seq); break; }
            const uint32_t session = protocol::readU32(p);
            if (!session) { sendAck(type, protocol::AckResult::NoSession, seq); break; }
            safety_manager.disarm();
            active_session = session;
            uart_keepalive_seen = true;
            last_uart_keepalive_ms = now;
            sendAck(type, protocol::AckResult::Ok, seq);
            sendHello();
            break;
        }
        case protocol::MessageType::Keepalive:
            if (!validSession(p, len)) sendAck(type, protocol::AckResult::SessionMismatch, seq);
            else { uart_keepalive_seen = true; last_uart_keepalive_ms = now; sendAck(type, protocol::AckResult::Ok, seq); }
            break;
        case protocol::MessageType::StatusRequest:
            sendStatus(now);
            break;
        case protocol::MessageType::Disarm:
            if (!validSession(p, len)) sendAck(type, protocol::AckResult::SessionMismatch, seq);
            else { safety_manager.disarm(); sendAck(type, protocol::AckResult::Ok, seq); }
            break;
        case protocol::MessageType::ArmRequest:
            if (!validSession(p, len)) sendAck(type, protocol::AckResult::SessionMismatch, seq);
            else sendAck(type, safety_manager.requestArm(), seq);
            break;
        case protocol::MessageType::SetRemotePower: {
            if (!validSession(p, len) || len < 6) { sendAck(type, protocol::AckResult::SessionMismatch, seq); break; }
            const uint8_t ch = p[4]; const bool en = p[5] != 0;
            if (ch >= 8) { sendAck(type, protocol::AckResult::InvalidChannel, seq, ch); break; }
            if (safety_manager.globalAllowAsserted()) { sendAck(type, protocol::AckResult::UnsafeState, seq, ch); break; }
            const bool ok = setRemotePower(ch, en);
            sendAck(type, ok ? protocol::AckResult::Ok : protocol::AckResult::DevOutputLocked, seq, ch);
            break;
        }
        case protocol::MessageType::SetCanEnable: {
            if (!validSession(p, len) || len < 6) { sendAck(type, protocol::AckResult::SessionMismatch, seq); break; }
            const uint8_t ch = p[4]; const bool en = p[5] != 0;
            if (ch >= 8) { sendAck(type, protocol::AckResult::InvalidChannel, seq, ch); break; }
            const bool ok = setCanEnable(ch, en);
            sendAck(type, ok ? protocol::AckResult::Ok : protocol::AckResult::PeripheralFault, seq, ch);
            break;
        }
        case protocol::MessageType::EnterService: {
            if (!validSession(p, len) || len < 5) { sendAck(type, protocol::AckResult::SessionMismatch, seq); break; }
            const uint8_t ch = p[4];
            if (ch >= 8) { sendAck(type, protocol::AckResult::InvalidChannel, seq, ch); break; }
            safety_manager.enterService(ch);
            setRemotePower(ch, false);
            setCanEnable(ch, false);
            sendAck(type, protocol::AckResult::Ok, seq, ch);
            break;
        }
        case protocol::MessageType::ExitService:
            if (!validSession(p, len)) sendAck(type, protocol::AckResult::SessionMismatch, seq);
            else { safety_manager.exitService(); sendAck(type, protocol::AckResult::Ok, seq); }
            break;
        case protocol::MessageType::ClearFaults:
            if (!validSession(p, len) || len < 8) sendAck(type, protocol::AckResult::SessionMismatch, seq);
            else { safety_manager.clearRecoverableFaults(protocol::readU32(&p[4])); sendAck(type, protocol::AckResult::Ok, seq); }
            break;
        default:
            break;
    }
}

static void pollPiUart(uint32_t now) {
    while (Serial1.available()) {
        const uint8_t b = uint8_t(Serial1.read());
        if (uart_rx_used == 0 && b != protocol::MAGIC0) continue;
        if (uart_rx_used == 1 && b != protocol::MAGIC1) { uart_rx_used = (b == protocol::MAGIC0) ? 1 : 0; continue; }
        uart_rx[uart_rx_used++] = b;
        if (uart_rx_used < protocol::FRAME_SIZE) continue;
        protocol::MessageType type; uint16_t seq; const uint8_t* payload; uint8_t len;
        if (protocol::decodeFrame(uart_rx, type, seq, payload, len)) handleCommand(type, seq, payload, len, now);
        uart_rx_used = 0;
    }
}

static void updateHeartbeat(uint32_t now) {
    const int level = digitalRead(pins::PI_HEARTBEAT);
    if (level != last_pi_hb_level) {
        last_pi_hb_level = level;
        last_pi_hb_edge_ms = now;
        pi_hb_edge_seen = true;
    }
}

static safety::Inputs collectInputs(uint32_t now) {
    safety::Inputs in;
    in.estop_healthy = digitalRead(pins::ESTOP_SENSE) == LOW;
    in.pi_heartbeat_ok = pi_hb_edge_seen && uint32_t(now - last_pi_hb_edge_ms) <= board::PI_HEARTBEAT_TIMEOUT_MS;
    in.uart_keepalive_ok = uart_keepalive_seen && uint32_t(now - last_uart_keepalive_ms) <= board::UART_KEEPALIVE_TIMEOUT_MS;
    in.pi_buck_pg = digitalRead(pins::PI_BUCK_PG) == HIGH;
    in.power_fault_clear = digitalRead(pins::PWR_FAULT_N) == HIGH;
    in.control_io_ok = control_io_ok;
    in.status_io_ok = status_io_ok;
    in.adc_ok = adc_ok;
    in.session_valid = active_session != 0;
    return in;
}

void setup() {
    safety_manager.begin();
    pinMode(pins::PI_HEARTBEAT, INPUT);
    pinMode(pins::SUP_IO_INT_N, INPUT);
    pinMode(pins::PWR_FAULT_N, INPUT);
    pinMode(pins::PI_BUCK_PG, INPUT);
    pinMode(pins::ESTOP_SENSE, INPUT);
    pinMode(pins::CCB_FAULT_LED, OUTPUT); digitalWrite(pins::CCB_FAULT_LED, LOW);
    pinMode(pins::CCB_RGB_DATA, OUTPUT); digitalWrite(pins::CCB_RGB_DATA, LOW);

    Serial.begin(board::DEBUG_BAUD);
    Serial1.begin(board::PI_UART_BAUD);
    Wire.begin();
    Wire.setClock(board::I2C_CLOCK_HZ);

    control_io_ok = control_io.initializeControlExpander();
    status_io_ok = status_io.initializeStatusExpander();
    adc_ok = current_adc.probe();
    remote_enable_mask = 0;
    can_enable_mask = 0;
    remote_pg_mask = 0;
    last_pi_hb_level = digitalRead(pins::PI_HEARTBEAT);

    sendHello();
}

void loop() {
    const uint32_t now = millis();
    updateHeartbeat(now);
    pollPiUart(now);

    if (status_io_ok) {
        uint8_t pg = 0;
        if (status_io.readPort1(pg)) remote_pg_mask = pg;
        else status_io_ok = false;
    }

    safety_manager.update(collectInputs(now));
    digitalWrite(pins::CCB_FAULT_LED, safety_manager.faults() ? HIGH : LOW);

    if (uint32_t(now - last_status_ms) >= board::STATUS_INTERVAL_MS) {
        last_status_ms = now;
        sendStatus(now);
    }
    if (uint32_t(now - last_hello_ms) >= board::HELLO_INTERVAL_MS) {
        last_hello_ms = now;
        sendHello();
    }
}
