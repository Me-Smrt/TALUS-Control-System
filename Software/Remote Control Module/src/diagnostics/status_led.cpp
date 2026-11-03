#include "status_led.h"
#include "../board/pins.h"
#include <Arduino.h>

namespace automaton::diagnostics {
void StatusLed::begin() {
    // Stay high-impedance until external 5V_LOGIC is confirmed. This avoids
    // using a USB-powered MCU GPIO to back-power an external LED circuit.
    pinMode(pins::RCB_STATUS_LED, INPUT);
}

void StatusLed::update(uint32_t now_ms, protocol::RcbState state, uint32_t faults, bool identify_flash) {
    if (state == protocol::RcbState::UsbOnly || state == protocol::RcbState::SafeBoot) {
        pinMode(pins::RCB_STATUS_LED, INPUT);
        return;
    }

    pinMode(pins::RCB_STATUS_LED, OUTPUT);
    bool on = false;
    if (identify_flash) on = ((now_ms / 100) % 2) == 0;
    else if (faults) on = ((now_ms / 150) % 2) == 0;
    else if (state == protocol::RcbState::ReadyDisarmed) on = true;
    else if (state == protocol::RcbState::Armed) on = ((now_ms / 500) % 2) == 0;
    digitalWrite(pins::RCB_STATUS_LED, on ? HIGH : LOW);
}
}
