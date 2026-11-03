#pragma once
#include <Arduino.h>
#include <Wire.h>
#include <stdint.h>

namespace automaton::ccb::drivers {
class Ads7138 {
public:
    Ads7138(TwoWire& wire, uint8_t address) : wire_(wire), address_(address) {}
    bool probe();

    // Conversion/current scaling is intentionally deferred until the TPS259830 IMON
    // transfer function and desired sampling/filter policy are frozen and bench-verified.
private:
    TwoWire& wire_;
    uint8_t address_;
};
}
