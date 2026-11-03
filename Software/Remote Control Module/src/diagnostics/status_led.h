#pragma once
#include "../protocol/messages.h"
#include <stdint.h>

namespace automaton::diagnostics {
class StatusLed {
public:
    void begin();
    void update(uint32_t now_ms, protocol::RcbState state, uint32_t faults, bool identify_flash);
};
}
