#pragma once
#include <stdint.h>

namespace automaton::diagnostics {

enum class ButtonEvent : uint8_t { None = 0, ShortPress = 1, LongPress = 2 };

class IdentifyButton {
public:
    void begin();
    ButtonEvent update(uint32_t now_ms);

private:
    bool stable_pressed_ = false;
    bool last_raw_pressed_ = false;
    uint32_t raw_changed_ms_ = 0;
    uint32_t pressed_since_ms_ = 0;
    bool long_sent_ = false;
};

}  // namespace automaton::diagnostics
