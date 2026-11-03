#pragma once
#include <stdint.h>
#include "../protocol/supervisor_protocol.h"

namespace automaton::ccb::safety {
struct Inputs {
    bool estop_healthy = false;
    bool pi_heartbeat_ok = false;
    bool uart_keepalive_ok = false;
    bool pi_buck_pg = false;
    bool power_fault_clear = false;
    bool control_io_ok = false;
    bool status_io_ok = false;
    bool adc_ok = false;
    bool session_valid = false;
};

class SafetyManager {
public:
    void begin();
    void update(const Inputs& in);
    protocol::AckResult requestArm();
    void disarm();
    void enterService(uint8_t channel);
    void exitService();

    protocol::SupervisorState state() const { return state_; }
    uint32_t faults() const { return faults_; }
    uint16_t statusBits() const;
    bool globalAllowAsserted() const { return global_allow_; }
    int8_t serviceChannel() const { return service_channel_; }
    void clearRecoverableFaults(uint32_t mask);

private:
    void setPhysicalGlobalAllow(bool enabled);
    bool allArmConditionsOk() const;

    Inputs in_{};
    protocol::SupervisorState state_ = protocol::SupervisorState::BootSafe;
    uint32_t faults_ = protocol::FAULT_NONE;
    bool global_allow_ = false;
    int8_t service_channel_ = -1;
};
}
