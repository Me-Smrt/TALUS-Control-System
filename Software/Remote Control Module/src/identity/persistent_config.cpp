#include "persistent_config.h"
#include "../board/board_config.h"
#include <Arduino.h>

#if __has_include(<EEPROM.h>)
#include <EEPROM.h>
#define AUTOMATON_HAS_EEPROM 1
#else
#define AUTOMATON_HAS_EEPROM 0
#endif

#if defined(ARDUINO_ARCH_RENESAS) && __has_include("bsp_api.h")
#include "bsp_api.h"
#define AUTOMATON_HAS_RA_UNIQUE_ID 1
#else
#define AUTOMATON_HAS_RA_UNIQUE_ID 0
#endif

namespace automaton::identity {
static constexpr uint32_t MAGIC = 0x52434231; // "RCB1"

uint32_t PersistentConfigStore::checksum(const PersistentConfig& cfg) const {
    const uint8_t* p = reinterpret_cast<const uint8_t*>(&cfg);
    uint32_t h = 2166136261u;
    for (size_t i = 0; i < sizeof(PersistentConfig) - sizeof(uint32_t); ++i) {
        h ^= p[i]; h *= 16777619u;
    }
    return h;
}

uint64_t PersistentConfigStore::hardwareUid64() {
#if AUTOMATON_HAS_RA_UNIQUE_ID
    const bsp_unique_id_t* id = R_BSP_UniqueIdGet();
    if (id != nullptr) {
        // 64-bit FNV-1a across all four 32-bit hardware-unique words.
        uint64_t h = 14695981039346656037ull;
        const uint8_t* bytes = reinterpret_cast<const uint8_t*>(id->unique_id_words);
        for (size_t i = 0; i < 16; ++i) {
            h ^= uint64_t(bytes[i]);
            h *= 1099511628211ull;
        }
        if (h != 0) return h;
    }
#endif
    return generateFallbackUid();
}

uint64_t PersistentConfigStore::generateFallbackUid() {
    // Non-RA build/test fallback. Nano R4 production builds should use hardwareUid64().
    uint64_t x = 0x9E3779B97F4A7C15ull ^ uint64_t(micros());
    for (int i = 0; i < 32; ++i) {
        x ^= uint64_t(analogRead(A6) & 0x0FFFu) << ((i % 4) * 12);
        x ^= uint64_t(micros()) * 0xBF58476D1CE4E5B9ull;
        x ^= x >> 30; x *= 0xBF58476D1CE4E5B9ull;
        x ^= x >> 27; x *= 0x94D049BB133111EBull;
        x ^= x >> 31;
        delayMicroseconds(37);
    }
    return x ? x : 1;
}

bool PersistentConfigStore::begin() {
    const uint64_t silicon_uid = hardwareUid64();
    PersistentConfig cfg{};
    if (load(cfg)) {
        // UID follows the physical MCU, not copied EEPROM contents. If a config image was
        // cloned between boards, repair the UID while preserving the explicitly stored role.
        if (cfg.uid != silicon_uid) {
            cfg.uid = silicon_uid;
            if (!save(cfg)) return false;
        }
        current_ = cfg;
        return true;
    }

    current_.magic = MAGIC;
    current_.config_version = board::CONFIG_VERSION;
    current_.role = uint8_t(protocol::Role::Unassigned);
    current_.uid = silicon_uid;
    current_.checksum = checksum(current_);
    return save(current_);
}

bool PersistentConfigStore::load(PersistentConfig& out) {
#if AUTOMATON_HAS_EEPROM
    EEPROM.get(0, out);
    if (out.magic != MAGIC || out.config_version != board::CONFIG_VERSION) return false;
    if (out.checksum != checksum(out)) return false;
    current_ = out;
    return true;
#else
    (void)out;
    return false;
#endif
}

bool PersistentConfigStore::save(const PersistentConfig& cfg_in) {
    PersistentConfig cfg = cfg_in;
    cfg.magic = MAGIC;
    cfg.config_version = board::CONFIG_VERSION;
    cfg.checksum = checksum(cfg);
#if AUTOMATON_HAS_EEPROM
    EEPROM.put(0, cfg);
    current_ = cfg;
    return true;
#else
    current_ = cfg;
    return false;
#endif
}

bool PersistentConfigStore::setRole(protocol::Role role) {
    current_.role = uint8_t(role);
    return save(current_);
}

}  // namespace automaton::identity
