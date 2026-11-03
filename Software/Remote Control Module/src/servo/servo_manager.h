#pragma once
#include <stdint.h>
#include "pwm_driver.h"

namespace automaton::servo {

struct ServoProfile {
    bool enabled = false;
    bool inverted = false;
    uint16_t min_pulse_us = 1000;
    uint16_t neutral_pulse_us = 1500;
    uint16_t max_pulse_us = 2000;
};

class ServoManager {
public:
    ServoManager(TwoWire& wire);

    bool begin();
    bool pca0Present() const { return pca0_.healthy(); }
    bool pca1Present() const { return pca1_.healthy(); }
    bool allPresent() const { return pca0Present() && pca1Present(); }

    bool setProfile(uint8_t channel, const ServoProfile& profile);
    const ServoProfile* profile(uint8_t channel) const;

    // position_permille is a normalized local actuator goal in [-1000, +1000].
    // It deliberately does not expose raw PCA9685 counts to the host protocol.
    bool commandNormalized(uint8_t channel, int16_t position_permille, bool outputs_authorized);
    bool disableChannel(uint8_t channel);
    void disableAll();

private:
    uint16_t mapNormalizedToPulse(const ServoProfile& p, int16_t position_permille) const;
    Pca9685Driver& pcaForChannel(uint8_t channel);
    uint8_t localChannel(uint8_t channel) const { return uint8_t(channel & 0x0Fu); }

    TwoWire& wire_;
    Pca9685Driver pca0_;
    Pca9685Driver pca1_;
    ServoProfile profiles_[32]{};
};

}  // namespace automaton::servo
