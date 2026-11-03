#include "servo_manager.h"
#include "../board/board_config.h"
#include <Arduino.h>

namespace automaton::servo {

ServoManager::ServoManager(TwoWire& wire)
    : wire_(wire), pca0_(wire, board::PCA0_ADDRESS), pca1_(wire, board::PCA1_ADDRESS) {}

bool ServoManager::begin() {
    wire_.begin();
    wire_.setClock(board::I2C_CLOCK_HZ);
    const bool ok0 = pca0_.begin(board::SERVO_PWM_HZ, board::PCA9685_OSC_HZ);
    const bool ok1 = pca1_.begin(board::SERVO_PWM_HZ, board::PCA9685_OSC_HZ);
    disableAll();
    return ok0 && ok1;
}

bool ServoManager::setProfile(uint8_t channel, const ServoProfile& profile_in) {
    if (channel >= 32) return false;
    if (profile_in.min_pulse_us >= profile_in.neutral_pulse_us ||
        profile_in.neutral_pulse_us >= profile_in.max_pulse_us) return false;
    if (profile_in.min_pulse_us < board::ABS_MIN_SERVO_PULSE_US ||
        profile_in.max_pulse_us > board::ABS_MAX_SERVO_PULSE_US) return false;
    profiles_[channel] = profile_in;
    return true;
}

const ServoProfile* ServoManager::profile(uint8_t channel) const {
    return channel < 32 ? &profiles_[channel] : nullptr;
}

uint16_t ServoManager::mapNormalizedToPulse(const ServoProfile& p, int16_t position_permille) const {
    int32_t pos = position_permille;
    if (pos < -1000) pos = -1000;
    if (pos > 1000) pos = 1000;
    if (p.inverted) pos = -pos;

    if (pos < 0) {
        const int32_t span = int32_t(p.neutral_pulse_us) - int32_t(p.min_pulse_us);
        return uint16_t(int32_t(p.neutral_pulse_us) + (span * pos) / 1000);
    }
    const int32_t span = int32_t(p.max_pulse_us) - int32_t(p.neutral_pulse_us);
    return uint16_t(int32_t(p.neutral_pulse_us) + (span * pos) / 1000);
}

Pca9685Driver& ServoManager::pcaForChannel(uint8_t channel) {
    return channel < 16 ? pca0_ : pca1_;
}

bool ServoManager::commandNormalized(uint8_t channel, int16_t position_permille, bool outputs_authorized) {
    if (channel >= 32 || !outputs_authorized) return false;
    const ServoProfile& p = profiles_[channel];
    if (!p.enabled) return false;
    return pcaForChannel(channel).setChannelPulseUs(localChannel(channel), mapNormalizedToPulse(p, position_permille));
}

bool ServoManager::disableChannel(uint8_t channel) {
    if (channel >= 32) return false;
    return pcaForChannel(channel).setChannelOff(localChannel(channel));
}

void ServoManager::disableAll() {
    pca0_.setAllOff();
    pca1_.setAllOff();
}

}  // namespace automaton::servo
