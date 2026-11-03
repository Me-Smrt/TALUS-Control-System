#pragma once
#include <stdint.h>
#include "../protocol/messages.h"

namespace automaton::identity {

struct PersistentConfig {
    uint32_t magic = 0;
    uint8_t config_version = 0;
    uint8_t role = 0;
    uint16_t reserved = 0;
    uint64_t uid = 0;
    uint32_t checksum = 0;
};

class PersistentConfigStore {
public:
    bool begin();
    bool load(PersistentConfig& out);
    bool save(const PersistentConfig& cfg);
    bool setRole(protocol::Role role);
    const PersistentConfig& current() const { return current_; }

    // Protocol v1 uses a compact 64-bit RCB UID. On RA4M1 this is a deterministic
    // FNV-1a reduction of all 128 silicon-unique ID bits, not a random generated ID.
    static uint64_t hardwareUid64();

private:
    PersistentConfig current_{};
    uint32_t checksum(const PersistentConfig& cfg) const;
    static uint64_t generateFallbackUid();
};

}  // namespace automaton::identity
