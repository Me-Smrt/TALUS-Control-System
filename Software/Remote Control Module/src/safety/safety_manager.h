#pragma once
#include <stdint.h>
#include "../protocol/messages.h"

namespace automaton::safety {

struct SafetyInputs {
    bool logic_power_ok = false;
    bool can_ok = false;
    bool global_allow = false;
    bool pca0_present = false;
    bool pca1_present = false;
    bool bank_pg[4] = {false, false, false, false};
    bool config_valid = false;
    bool session_valid = false;
};

class SafetyManager {
public:
    void begin();
    void setState(protocol::RcbState state) { state_ = state; }
    protocol::RcbState state() const { return state_; }

    void updateInputs(const SafetyInputs& in);
    protocol::AckResult requestArm(uint32_t now_ms);
    void disarm(protocol::DisarmReason reason);
    void noteHeartbeat(uint32_t now_ms);
    void tick(uint32_t now_ms);

    uint16_t statusBits() const;
    uint32_t faults() const { return faults_; }
    bool sessionFresh(uint32_t now_ms) const;
    bool localEnable() const { return local_enable_; }
    bool motionAuthorized() const { return state_ == protocol::RcbState::Armed && local_enable_ && in_.global_allow; }

    void setFault(uint32_t bit) { faults_ |= bit; }
    void clearFault(uint32_t bit) { faults_ &= ~bit; }

private:
    void forceLocalEnable(bool enabled);
    bool allBanksPowerGood() const;
    void setMissingBankFaults();

    protocol::RcbState state_ = protocol::RcbState::Reset;
    SafetyInputs in_{};
    uint32_t faults_ = protocol::FAULT_NONE;
    uint32_t last_heartbeat_ms_ = 0;
    uint32_t arm_started_ms_ = 0;
    bool heartbeat_seen_ = false;
    bool local_enable_ = false;
};

}  // namespace automaton::safety
