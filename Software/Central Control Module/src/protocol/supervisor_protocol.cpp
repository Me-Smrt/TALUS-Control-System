#include "supervisor_protocol.h"
#include <string.h>

namespace automaton::ccb::protocol {
uint16_t crc16Ccitt(const uint8_t* data, size_t len) {
    uint16_t crc = 0xFFFF;
    for (size_t i = 0; i < len; ++i) {
        crc ^= uint16_t(data[i]) << 8;
        for (uint8_t bit = 0; bit < 8; ++bit)
            crc = (crc & 0x8000) ? uint16_t((crc << 1) ^ 0x1021) : uint16_t(crc << 1);
    }
    return crc;
}
uint16_t readU16(const uint8_t* p) { return uint16_t(p[0]) | (uint16_t(p[1]) << 8); }
uint32_t readU32(const uint8_t* p) { return uint32_t(p[0]) | (uint32_t(p[1]) << 8) | (uint32_t(p[2]) << 16) | (uint32_t(p[3]) << 24); }
void writeU16(uint8_t* p, uint16_t v) { p[0] = uint8_t(v); p[1] = uint8_t(v >> 8); }
void writeU32(uint8_t* p, uint32_t v) { for (uint8_t i = 0; i < 4; ++i) p[i] = uint8_t(v >> (8 * i)); }

bool decodeFrame(const uint8_t raw[FRAME_SIZE], MessageType& type, uint16_t& seq,
                 const uint8_t*& payload, uint8_t& payload_len) {
    if (raw[0] != MAGIC0 || raw[1] != MAGIC1 || raw[2] != VERSION) return false;
    payload_len = raw[6];
    if (payload_len > PAYLOAD_SIZE) return false;
    const uint16_t expected = readU16(&raw[30]);
    if (crc16Ccitt(raw, 30) != expected) return false;
    type = static_cast<MessageType>(raw[3]);
    seq = readU16(&raw[4]);
    payload = &raw[8];
    return true;
}

Frame encodeFrame(MessageType type, uint16_t seq, const uint8_t* payload, uint8_t payload_len) {
    Frame f{};
    f.raw[0] = MAGIC0; f.raw[1] = MAGIC1; f.raw[2] = VERSION; f.raw[3] = uint8_t(type);
    writeU16(&f.raw[4], seq);
    if (payload_len > PAYLOAD_SIZE) payload_len = PAYLOAD_SIZE;
    f.raw[6] = payload_len;
    f.raw[7] = 0;
    if (payload && payload_len) memcpy(&f.raw[8], payload, payload_len);
    writeU16(&f.raw[30], crc16Ccitt(f.raw, 30));
    return f;
}
}
