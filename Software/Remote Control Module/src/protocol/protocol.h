#pragma once
#include "messages.h"

namespace automaton::protocol {

uint16_t read_u16(const uint8_t* p);
uint32_t read_u32(const uint8_t* p);
uint64_t read_u64(const uint8_t* p);
void write_u16(uint8_t* p, uint16_t v);
void write_u32(uint8_t* p, uint32_t v);
void write_u64(uint8_t* p, uint64_t v);

CanFrame makeHelloUid(uint64_t uid);
CanFrame makeHelloMeta(Role role, uint8_t reset_reason);
CanFrame makeHelloCaps(const Capabilities& caps);
CanFrame makeHelloState(RcbState state, uint16_t status, uint32_t faults);
CanFrame makeStatus(RcbState state, Role role, uint16_t status, uint32_t faults);
CanFrame makeIdentify(uint64_t uid);
CanFrame makeArmAck(AckResult result, uint32_t session, uint16_t seq);
CanFrame makeConfigAck(AckResult result, uint32_t session, uint16_t seq);
CanFrame makePong(uint32_t session, uint16_t nonce, RcbState state);

bool checkProtocol(const CanFrame& frame);
bool parseSessionSeq(const CanFrame& frame, uint32_t& session, uint16_t& seq);

}  // namespace automaton::protocol
