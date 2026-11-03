#include "protocol.h"
#include "../board/board_config.h"

namespace automaton::protocol {

uint16_t read_u16(const uint8_t* p) { return uint16_t(p[0]) | (uint16_t(p[1]) << 8); }
uint32_t read_u32(const uint8_t* p) { return uint32_t(p[0]) | (uint32_t(p[1]) << 8) | (uint32_t(p[2]) << 16) | (uint32_t(p[3]) << 24); }
uint64_t read_u64(const uint8_t* p) {
    uint64_t v = 0;
    for (int i = 7; i >= 0; --i) v = (v << 8) | p[i];
    return v;
}
void write_u16(uint8_t* p, uint16_t v) { p[0] = uint8_t(v); p[1] = uint8_t(v >> 8); }
void write_u32(uint8_t* p, uint32_t v) { for (int i=0;i<4;++i) p[i] = uint8_t(v >> (8*i)); }
void write_u64(uint8_t* p, uint64_t v) { for (int i=0;i<8;++i) p[i] = uint8_t(v >> (8*i)); }

CanFrame makeHelloUid(uint64_t uid) {
    CanFrame f; f.id = uint16_t(CanId::HelloUid); write_u64(f.data, uid); return f;
}
CanFrame makeHelloMeta(Role role, uint8_t reset_reason) {
    CanFrame f; f.id = uint16_t(CanId::HelloMeta);
    f.data[0] = board::PROTOCOL_VERSION; f.data[1] = uint8_t(role);
    f.data[2] = board::HARDWARE_REVISION; f.data[3] = board::CONFIG_VERSION;
    f.data[4] = board::FW_MAJOR; f.data[5] = board::FW_MINOR; f.data[6] = board::FW_PATCH;
    f.data[7] = reset_reason; return f;
}
CanFrame makeHelloCaps(const Capabilities& caps) {
    CanFrame f; f.id = uint16_t(CanId::HelloCaps);
    f.data[0] = caps.pwm_channel_count; f.data[1] = caps.bank_count; f.data[2] = caps.supported_bank_mask;
    write_u16(&f.data[3], caps.feature_flags); return f;
}
CanFrame makeHelloState(RcbState state, uint16_t status, uint32_t faults) {
    CanFrame f; f.id = uint16_t(CanId::HelloState); f.data[0] = uint8_t(state);
    write_u16(&f.data[1], status); write_u32(&f.data[3], faults); f.data[7] = 0; return f;
}
CanFrame makeStatus(RcbState state, Role role, uint16_t status, uint32_t faults) {
    CanFrame f; f.id = uint16_t(CanId::Status); f.data[0] = uint8_t(state); f.data[1] = uint8_t(role);
    write_u16(&f.data[2], status); write_u32(&f.data[4], faults); return f;
}
CanFrame makeIdentify(uint64_t uid) { CanFrame f; f.id = uint16_t(CanId::Identify); write_u64(f.data, uid); return f; }
CanFrame makeArmAck(AckResult result, uint32_t session, uint16_t seq) {
    CanFrame f; f.id = uint16_t(CanId::ArmAck); f.data[0] = board::PROTOCOL_VERSION; f.data[1] = uint8_t(result);
    write_u32(&f.data[2], session); write_u16(&f.data[6], seq); return f;
}
CanFrame makeConfigAck(AckResult result, uint32_t session, uint16_t seq) {
    CanFrame f; f.id = uint16_t(CanId::ConfigAck); f.data[0] = board::PROTOCOL_VERSION; f.data[1] = uint8_t(result);
    write_u32(&f.data[2], session); write_u16(&f.data[6], seq); return f;
}
CanFrame makePong(uint32_t session, uint16_t nonce, RcbState state) {
    CanFrame f; f.id = uint16_t(CanId::Pong); f.data[0] = board::PROTOCOL_VERSION;
    write_u32(&f.data[1], session); write_u16(&f.data[5], nonce); f.data[7] = uint8_t(state); return f;
}

bool checkProtocol(const CanFrame& frame) { return frame.dlc == 8 && frame.data[0] == board::PROTOCOL_VERSION; }
bool parseSessionSeq(const CanFrame& frame, uint32_t& session, uint16_t& seq) {
    if (!checkProtocol(frame)) return false;
    session = read_u32(&frame.data[1]); seq = read_u16(&frame.data[5]); return true;
}

}  // namespace automaton::protocol
