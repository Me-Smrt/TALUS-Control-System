#include "identify_button.h"
#include "../board/pins.h"
#include "../board/board_config.h"
#include <Arduino.h>

namespace automaton::diagnostics {
void IdentifyButton::begin() { pinMode(pins::RCB_IDENTIFY_N, INPUT); }

ButtonEvent IdentifyButton::update(uint32_t now_ms) {
    const bool raw_pressed = digitalRead(pins::RCB_IDENTIFY_N) == LOW;
    if (raw_pressed != last_raw_pressed_) { last_raw_pressed_ = raw_pressed; raw_changed_ms_ = now_ms; }
    if (uint32_t(now_ms - raw_changed_ms_) < board::IDENTIFY_DEBOUNCE_MS) return ButtonEvent::None;

    if (raw_pressed != stable_pressed_) {
        stable_pressed_ = raw_pressed;
        if (stable_pressed_) { pressed_since_ms_ = now_ms; long_sent_ = false; }
        else if (!long_sent_) { return ButtonEvent::ShortPress; }
    }

    if (stable_pressed_ && !long_sent_ && uint32_t(now_ms - pressed_since_ms_) >= board::IDENTIFY_LONG_PRESS_MS) {
        long_sent_ = true;
        return ButtonEvent::LongPress;
    }
    return ButtonEvent::None;
}
}  // namespace automaton::diagnostics
