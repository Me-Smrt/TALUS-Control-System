#include "pwm_driver.h"
#include <Arduino.h>
#include <math.h>

namespace automaton::servo {
namespace {
constexpr uint8_t MODE1 = 0x00;
constexpr uint8_t MODE2 = 0x01;
constexpr uint8_t LED0_ON_L = 0x06;
constexpr uint8_t ALL_LED_ON_L = 0xFA;
constexpr uint8_t PRE_SCALE = 0xFE;

constexpr uint8_t MODE1_RESTART = 0x80;
constexpr uint8_t MODE1_AI = 0x20;
constexpr uint8_t MODE1_SLEEP = 0x10;
constexpr uint8_t MODE2_OUTDRV = 0x04;
constexpr uint8_t FULL_OFF = 0x10;
}

bool Pca9685Driver::probe() {
    uint8_t mode = 0;
    healthy_ = readRegister(MODE1, mode);
    return healthy_;
}

bool Pca9685Driver::writeRegister(uint8_t reg, uint8_t value) {
    wire_.beginTransmission(address_);
    wire_.write(reg);
    wire_.write(value);
    return wire_.endTransmission() == 0;
}

bool Pca9685Driver::writeRegisters(uint8_t start_reg, const uint8_t* data, uint8_t len) {
    wire_.beginTransmission(address_);
    wire_.write(start_reg);
    for (uint8_t i = 0; i < len; ++i) wire_.write(data[i]);
    return wire_.endTransmission() == 0;
}

bool Pca9685Driver::readRegister(uint8_t reg, uint8_t& value) {
    wire_.beginTransmission(address_);
    wire_.write(reg);
    if (wire_.endTransmission(false) != 0) return false;
    if (wire_.requestFrom(address_, uint8_t(1)) != 1) return false;
    value = uint8_t(wire_.read());
    return true;
}

bool Pca9685Driver::setAllOff() {
    // Do not rely on MODE1.AI here: AI is not guaranteed enabled at power-on and this
    // function is intentionally used *before* frequency setup.  Explicit writes make the
    // first safe-state command deterministic from a true PCA9685 reset.
    bool ok = true;
    ok = writeRegister(ALL_LED_ON_L + 0u, 0) && ok;
    ok = writeRegister(ALL_LED_ON_L + 1u, 0) && ok;
    ok = writeRegister(ALL_LED_ON_L + 2u, 0) && ok;
    ok = writeRegister(ALL_LED_ON_L + 3u, FULL_OFF) && ok;
    healthy_ = healthy_ && ok;
    return ok;
}

bool Pca9685Driver::setChannelOff(uint8_t channel) {
    if (channel >= 16) return false;
    const uint8_t data[4] = {0, 0, 0, FULL_OFF};
    const bool ok = writeRegisters(uint8_t(LED0_ON_L + 4u * channel), data, sizeof(data));
    healthy_ = healthy_ && ok;
    return ok;
}

bool Pca9685Driver::setFrequency(float pwm_hz, uint32_t oscillator_hz) {
    if (pwm_hz < 24.0f || pwm_hz > 1526.0f || oscillator_hz == 0) return false;

    float prescale_f = (float(oscillator_hz) / (4096.0f * pwm_hz)) - 1.0f;
    long prescale = lroundf(prescale_f);
    if (prescale < 3) prescale = 3;
    if (prescale > 255) prescale = 255;

    uint8_t old_mode = 0;
    if (!readRegister(MODE1, old_mode)) return false;
    const uint8_t sleep_mode = uint8_t((old_mode & ~MODE1_RESTART) | MODE1_SLEEP | MODE1_AI);
    if (!writeRegister(MODE1, sleep_mode)) return false;
    if (!writeRegister(PRE_SCALE, uint8_t(prescale))) return false;
    if (!writeRegister(MODE1, uint8_t((old_mode | MODE1_AI) & ~MODE1_SLEEP))) return false;
    delayMicroseconds(600); // PCA9685 oscillator wake-up requirement is <=500 us.
    if (!writeRegister(MODE1, uint8_t((old_mode | MODE1_AI | MODE1_RESTART) & ~MODE1_SLEEP))) return false;

    oscillator_hz_ = oscillator_hz;
    pwm_hz_ = float(oscillator_hz) / (4096.0f * float(prescale + 1));
    return true;
}

bool Pca9685Driver::begin(float pwm_hz, uint32_t oscillator_hz) {
    healthy_ = false;
    if (!probe()) return false;

    // Keep all outputs logically OFF before any timing configuration. Hardware OE is also
    // held inactive by the independent RCB safety chain during this entire sequence.
    if (!setAllOff()) return false;
    if (!writeRegister(MODE2, MODE2_OUTDRV)) return false;
    if (!setFrequency(pwm_hz, oscillator_hz)) return false;
    if (!setAllOff()) return false;
    healthy_ = true;
    return true;
}

bool Pca9685Driver::setChannelPulseUs(uint8_t channel, uint16_t pulse_us) {
    if (!healthy_ || channel >= 16 || pwm_hz_ <= 0.0f) return false;
    const float ticks_f = (float(pulse_us) * pwm_hz_ * 4096.0f) / 1000000.0f;
    long ticks = lroundf(ticks_f);
    if (ticks < 1) ticks = 1;
    if (ticks > 4095) ticks = 4095;

    const uint16_t off = uint16_t(ticks);
    const uint8_t data[4] = {
        0, 0,
        uint8_t(off & 0xFFu),
        uint8_t((off >> 8) & 0x0Fu),
    };
    const bool ok = writeRegisters(uint8_t(LED0_ON_L + 4u * channel), data, sizeof(data));
    healthy_ = healthy_ && ok;
    return ok;
}

}  // namespace automaton::servo
