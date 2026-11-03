#include "can_driver.h"
#include "../board/pins.h"
#include "../board/board_config.h"
#include <Arduino.h>
#include <limits.h>

namespace automaton::canbus {
namespace {
constexpr uint32_t HEALTH_POLL_MS = 100;
constexpr uint32_t MODE_CHANGE_TIMEOUT_US = 50000;
constexpr uint32_t MAX_BITRATE_ERROR_PPM = 5000; // 0.5%

static uint32_t absDiff(uint32_t a, uint32_t b) { return a > b ? a - b : b - a; }
}

bool Mcp25625Driver::calculateBitTiming(uint32_t oscillator_hz, uint32_t target_bitrate, BitTiming& out) {
    if (oscillator_hz == 0 || target_bitrate == 0) return false;

    bool found = false;
    uint32_t best_error = UINT32_MAX;
    uint32_t best_sample_error = UINT32_MAX;
    uint8_t best_tq = 0;
    BitTiming best{};

    // MCP2515/MCP25625 nominal bit time:
    // bitrate = Fosc / (2 * (BRP + 1) * N_TQ)
    // N_TQ = SyncSeg(1) + PropSeg + PhaseSeg1 + PhaseSeg2.
    // A target sample point of ~80% is a conservative first-stage default.
    constexpr uint16_t target_sample_permille = 800;

    for (uint8_t brp = 0; brp <= 63; ++brp) {
        for (uint8_t prop = 1; prop <= 8; ++prop) {
            for (uint8_t ps1 = 1; ps1 <= 8; ++ps1) {
                for (uint8_t ps2 = 2; ps2 <= 8; ++ps2) {
                    const uint8_t ntq = uint8_t(1 + prop + ps1 + ps2);
                    if (ntq < 8 || ntq > 25) continue;
                    const uint32_t divisor = 2u * uint32_t(brp + 1u) * uint32_t(ntq);
                    const uint32_t actual = oscillator_hz / divisor;
                    if (actual == 0) continue;
                    const uint32_t err = uint32_t((uint64_t(absDiff(actual, target_bitrate)) * 1000000ull) / target_bitrate);
                    const uint16_t sample = uint16_t((uint32_t(1 + prop + ps1) * 1000u) / ntq);
                    const uint32_t sample_err = absDiff(sample, target_sample_permille);

                    if (!found || err < best_error ||
                        (err == best_error && sample_err < best_sample_error) ||
                        (err == best_error && sample_err == best_sample_error && ntq > best_tq)) {
                        found = true;
                        best_error = err;
                        best_sample_error = sample_err;
                        best_tq = ntq;
                        best.brp = brp;
                        best.prop_seg = prop;
                        best.phase_seg1 = ps1;
                        best.phase_seg2 = ps2;
                        best.sjw = 1;
                        best.actual_bitrate = actual;
                        best.sample_point_permille = sample;
                        best.error_ppm = err;
                    }
                }
            }
        }
    }

    if (!found || best.error_ppm > MAX_BITRATE_ERROR_PPM) return false;
    out = best;
    return true;
}

void Mcp25625Driver::beginTransaction() {
    SPI.beginTransaction(spi_settings_);
    digitalWrite(pins::CAN_CS_N, LOW);
}

void Mcp25625Driver::endTransaction() {
    digitalWrite(pins::CAN_CS_N, HIGH);
    SPI.endTransaction();
}

void Mcp25625Driver::resetController() {
    beginTransaction();
    SPI.transfer(INSTR_RESET);
    endTransaction();
    delay(10);
}

uint8_t Mcp25625Driver::readRegister(uint8_t address) {
    beginTransaction();
    SPI.transfer(INSTR_READ);
    SPI.transfer(address);
    const uint8_t value = SPI.transfer(0x00);
    endTransaction();
    return value;
}

void Mcp25625Driver::readRegisters(uint8_t address, uint8_t* data, uint8_t length) {
    beginTransaction();
    SPI.transfer(INSTR_READ);
    SPI.transfer(address);
    for (uint8_t i = 0; i < length; ++i) data[i] = SPI.transfer(0x00);
    endTransaction();
}

void Mcp25625Driver::writeRegister(uint8_t address, uint8_t value) {
    beginTransaction();
    SPI.transfer(INSTR_WRITE);
    SPI.transfer(address);
    SPI.transfer(value);
    endTransaction();
}

void Mcp25625Driver::writeRegisters(uint8_t address, const uint8_t* data, uint8_t length) {
    beginTransaction();
    SPI.transfer(INSTR_WRITE);
    SPI.transfer(address);
    for (uint8_t i = 0; i < length; ++i) SPI.transfer(data[i]);
    endTransaction();
}

void Mcp25625Driver::bitModify(uint8_t address, uint8_t mask, uint8_t value) {
    beginTransaction();
    SPI.transfer(INSTR_BIT_MODIFY);
    SPI.transfer(address);
    SPI.transfer(mask);
    SPI.transfer(value);
    endTransaction();
}

bool Mcp25625Driver::requestMode(uint8_t mode) {
    bitModify(REG_CANCTRL, MODE_MASK, mode & MODE_MASK);
    const uint32_t started = micros();
    while (uint32_t(micros() - started) < MODE_CHANGE_TIMEOUT_US) {
        if ((readRegister(REG_CANSTAT) & MODE_MASK) == (mode & MODE_MASK)) return true;
        delayMicroseconds(100);
    }
    return false;
}

bool Mcp25625Driver::configureController(uint32_t bitrate) {
    if (!calculateBitTiming(board::MCP25625_OSC_HZ, bitrate, bit_timing_)) return false;
    if (!requestMode(MODE_CONFIG)) return false;

    const uint8_t cnf1 = uint8_t(((bit_timing_.sjw - 1u) << 6) | (bit_timing_.brp & 0x3Fu));
    const uint8_t cnf2 = uint8_t(0x80u | ((bit_timing_.phase_seg1 - 1u) << 3) | (bit_timing_.prop_seg - 1u));
    const uint8_t cnf3 = uint8_t((bit_timing_.phase_seg2 - 1u) & 0x07u);
    writeRegister(REG_CNF1, cnf1);
    writeRegister(REG_CNF2, cnf2);
    writeRegister(REG_CNF3, cnf3);

    // Receive any valid standard 11-bit frame. Filters/masks remain zero after reset,
    // so standard-only mode accepts all standard identifiers while rejecting extended frames.
    writeRegister(REG_RXB0CTRL, 0x24); // RXM=01 (standard only), BUKT=1
    writeRegister(REG_RXB1CTRL, 0x20); // RXM=01 (standard only)
    writeRegister(REG_CANINTF, 0x00);
    writeRegister(REG_EFLG, 0x00);
    writeRegister(REG_CANINTE, CANINTF_RX0IF | CANINTF_RX1IF);

    if (!requestMode(MODE_NORMAL)) return false;
    configured_bitrate_ = bit_timing_.actual_bitrate;
    return true;
}

bool Mcp25625Driver::begin(uint32_t bitrate) {
    healthy_ = false;
    error_flags_ = tx_error_count_ = rx_error_count_ = 0;
    configured_bitrate_ = 0;

    // Keep the integrated transceiver in standby until the SPI controller has been fully configured.
    pinMode(pins::CAN_STBY, OUTPUT);
    digitalWrite(pins::CAN_STBY, HIGH);
    standby_ = true;

    pinMode(pins::CAN_CS_N, OUTPUT);
    digitalWrite(pins::CAN_CS_N, HIGH);
    pinMode(pins::CAN_INT_N, INPUT);

    SPI.begin();
    spi_settings_ = SPISettings(board::CAN_SPI_HZ, MSBFIRST, SPI_MODE0);
    resetController();

    if (!configureController(bitrate)) {
        setStandby(true);
        return false;
    }

    setStandby(false);
    healthy_ = true;
    last_health_poll_ms_ = millis();
    return true;
}

void Mcp25625Driver::setStandby(bool standby) {
    pinMode(pins::CAN_STBY, OUTPUT);
    digitalWrite(pins::CAN_STBY, standby ? HIGH : LOW);
    standby_ = standby;
}

bool Mcp25625Driver::loadTxBuffer(uint8_t ctrl_reg, const protocol::CanFrame& frame) {
    if (frame.id > 0x7FFu || frame.dlc > 8) return false;
    if (readRegister(ctrl_reg) & TXREQ) return false;

    const uint8_t base = uint8_t(ctrl_reg + 1u);
    uint8_t header[5]{};
    header[0] = uint8_t(frame.id >> 3);            // SIDH
    header[1] = uint8_t((frame.id & 0x07u) << 5); // SIDL, EXIDE=0
    header[2] = 0;                                 // EID8
    header[3] = 0;                                 // EID0
    header[4] = uint8_t(frame.dlc & 0x0Fu);       // DLC, RTR=0
    writeRegisters(base, header, sizeof(header));
    if (frame.dlc) writeRegisters(uint8_t(base + 5u), frame.data, frame.dlc);
    bitModify(ctrl_reg, TXREQ, TXREQ);
    return true;
}

bool Mcp25625Driver::send(const protocol::CanFrame& frame) {
    if (!healthy_ || standby_) return false;
    if (loadTxBuffer(REG_TXB0CTRL, frame)) return true;
    if (loadTxBuffer(REG_TXB1CTRL, frame)) return true;
    if (loadTxBuffer(REG_TXB2CTRL, frame)) return true;
    return false;
}

bool Mcp25625Driver::readRxBuffer(uint8_t ctrl_reg, protocol::CanFrame& frame) {
    const uint8_t base = uint8_t(ctrl_reg + 1u);
    uint8_t header[5]{};
    readRegisters(base, header, sizeof(header));

    // SIDL bit 3 is IDE for received frames. Only Classic CAN standard frames are accepted here.
    if (header[1] & 0x08u) return false;
    const uint8_t dlc = uint8_t(header[4] & 0x0Fu);
    if (dlc > 8 || (header[4] & 0x40u)) return false; // reject malformed/RTR frames

    frame.id = uint16_t((uint16_t(header[0]) << 3) | (header[1] >> 5));
    frame.dlc = dlc;
    for (uint8_t& byte : frame.data) byte = 0;
    if (dlc) readRegisters(uint8_t(base + 5u), frame.data, dlc);
    return true;
}

bool Mcp25625Driver::receive(protocol::CanFrame& frame) {
    if (!healthy_) return false;
    const uint8_t flags = readRegister(REG_CANINTF);
    if (flags & CANINTF_RX0IF) {
        const bool ok = readRxBuffer(REG_RXB0CTRL, frame);
        bitModify(REG_CANINTF, CANINTF_RX0IF, 0);
        return ok;
    }
    if (flags & CANINTF_RX1IF) {
        const bool ok = readRxBuffer(REG_RXB1CTRL, frame);
        bitModify(REG_CANINTF, CANINTF_RX1IF, 0);
        return ok;
    }
    return false;
}

void Mcp25625Driver::service(uint32_t now_ms) {
    if (!healthy_) return;
    if (uint32_t(now_ms - last_health_poll_ms_) < HEALTH_POLL_MS) return;
    last_health_poll_ms_ = now_ms;

    error_flags_ = readRegister(REG_EFLG);
    tx_error_count_ = readRegister(REG_TEC);
    rx_error_count_ = readRegister(REG_REC);
    const uint8_t mode = readRegister(REG_CANSTAT) & MODE_MASK;
    if ((error_flags_ & EFLG_TXBO) || mode != MODE_NORMAL) {
        healthy_ = false;
        setStandby(true);
    }
}

}  // namespace automaton::canbus
