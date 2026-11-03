#include "tca9535.h"

namespace automaton::ccb::drivers {
namespace {
constexpr uint8_t REG_INPUT0 = 0x00;
constexpr uint8_t REG_INPUT1 = 0x01;
constexpr uint8_t REG_OUTPUT0 = 0x02;
constexpr uint8_t REG_OUTPUT1 = 0x03;
constexpr uint8_t REG_POLARITY0 = 0x04;
constexpr uint8_t REG_POLARITY1 = 0x05;
constexpr uint8_t REG_CONFIG0 = 0x06;
constexpr uint8_t REG_CONFIG1 = 0x07;
}

bool Tca9535::probe() {
    wire_.beginTransmission(address_);
    return wire_.endTransmission() == 0;
}

bool Tca9535::writeReg(uint8_t reg, uint8_t value) {
    wire_.beginTransmission(address_);
    wire_.write(reg);
    wire_.write(value);
    return wire_.endTransmission() == 0;
}

bool Tca9535::readReg(uint8_t reg, uint8_t& value) {
    wire_.beginTransmission(address_);
    wire_.write(reg);
    if (wire_.endTransmission(false) != 0) return false;
    if (wire_.requestFrom(int(address_), 1) != 1) return false;
    value = wire_.read();
    return true;
}

bool Tca9535::initializeControlExpander() {
    // Safe ordering: preload both output latches LOW, disable inversion, then
    // make all pins outputs. Port 0 drives REMOTE_EN_0..7. Port 1 is physically
    // unused; driving it LOW prevents floating unused inputs from chattering INT.
    return probe() &&
           writeReg(REG_OUTPUT0, 0x00) && writeReg(REG_OUTPUT1, 0x00) &&
           writeReg(REG_POLARITY0, 0x00) && writeReg(REG_POLARITY1, 0x00) &&
           writeReg(REG_CONFIG0, 0x00) && writeReg(REG_CONFIG1, 0x00);
}

bool Tca9535::initializeStatusExpander() {
    // Port 0 = CAN_ENABLE_0..7 outputs, initially disabled.
    // Port 1 = REMOTE_PG_0..7 inputs.
    return probe() &&
           writeReg(REG_OUTPUT0, 0x00) &&
           writeReg(REG_POLARITY0, 0x00) && writeReg(REG_POLARITY1, 0x00) &&
           writeReg(REG_CONFIG0, 0x00) && writeReg(REG_CONFIG1, 0xFF);
}

bool Tca9535::setPort0(uint8_t value) { return writeReg(REG_OUTPUT0, value); }
bool Tca9535::readPort1(uint8_t& value) { return readReg(REG_INPUT1, value); }
}
