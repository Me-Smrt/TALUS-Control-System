#pragma once
#include <stdint.h>
#include <Wire.h>

namespace automaton::servo {

class Pca9685Driver {
public:
    Pca9685Driver(TwoWire& wire, uint8_t address) : wire_(wire), address_(address) {}

    bool begin(float pwm_hz, uint32_t oscillator_hz);
    bool probe();
    bool healthy() const { return healthy_; }
    uint8_t address() const { return address_; }
    float pwmFrequency() const { return pwm_hz_; }

    bool setAllOff();
    bool setChannelOff(uint8_t channel);
    bool setChannelPulseUs(uint8_t channel, uint16_t pulse_us);

private:
    bool writeRegister(uint8_t reg, uint8_t value);
    bool writeRegisters(uint8_t start_reg, const uint8_t* data, uint8_t len);
    bool readRegister(uint8_t reg, uint8_t& value);
    bool setFrequency(float pwm_hz, uint32_t oscillator_hz);

    TwoWire& wire_;
    uint8_t address_;
    bool healthy_ = false;
    float pwm_hz_ = 0.0f;
    uint32_t oscillator_hz_ = 0;
};

}  // namespace automaton::servo
