#pragma once
#include <Arduino.h>
#include <Wire.h>
#include <stdint.h>

namespace automaton::ccb::drivers {
class Tca9535 {
public:
    Tca9535(TwoWire& wire, uint8_t address) : wire_(wire), address_(address) {}
    bool probe();
    bool writeReg(uint8_t reg, uint8_t value);
    bool readReg(uint8_t reg, uint8_t& value);
    bool initializeControlExpander();
    bool initializeStatusExpander();
    bool setPort0(uint8_t value);
    bool readPort1(uint8_t& value);

private:
    TwoWire& wire_;
    uint8_t address_;
};
}
