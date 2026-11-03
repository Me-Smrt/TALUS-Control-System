#include "safety_manager.h"
#include "../board/pins.h"
#include "../board/board_config.h"
#include <Arduino.h>

namespace automaton::ccb::safety {
void SafetyManager::setPhysicalGlobalAllow(bool enabled) {
#if AUTOMATON_CCB_GLOBAL_SERVO_ALLOW_OUTPUT_ENABLED
    global_allow_ = enabled;
#else
    global_allow_ = false;
    (void)enabled;
#endif
    pinMode(pins::SUPERVISOR_ALLOW_REQ, OUTPUT);
    digitalWrite(pins::SUPERVISOR_ALLOW_REQ, global_allow_ ? HIGH : LOW);
}

void SafetyManager::begin() {
    // First safety action: force the request LOW. The physical E-stop chain still has
    // independent veto authority even when this output is later enabled.
    setPhysicalGlobalAllow(false);
    state_ = protocol::SupervisorState::BootSafe;
}

bool SafetyManager::allArmConditionsOk() const {
    return in_.estop_healthy && in_.pi_heartbeat_ok && in_.uart_keepalive_ok &&
           in_.pi_buck_pg && in_.power_fault_clear && in_.control_io_ok &&
           in_.status_io_ok && in_.adc_ok && in_.session_valid;
}

void SafetyManager::update(const Inputs& in) {
    const bool was_heartbeat = in_.pi_heartbeat_ok;
    const bool was_uart = in_.uart_keepalive_ok;
    const bool was_power = in_.pi_buck_pg && in_.power_fault_clear;
    in_ = in;

    if (!in_.estop_healthy) {
        setPhysicalGlobalAllow(false);
        state_ = protocol::SupervisorState::Estop;
        return;
    }
    if (was_heartbeat && !in_.pi_heartbeat_ok) faults_ |= protocol::FAULT_PI_HEARTBEAT_TIMEOUT;
    if (was_uart && !in_.uart_keepalive_ok) faults_ |= protocol::FAULT_UART_KEEPALIVE_TIMEOUT;
    if (was_power && (!in_.pi_buck_pg || !in_.power_fault_clear)) faults_ |= protocol::FAULT_PI_POWER;
    if (!in_.power_fault_clear) faults_ |= protocol::FAULT_PWR_FAULT_N;
    if (!in_.control_io_ok) faults_ |= protocol::FAULT_CONTROL_IO;
    if (!in_.status_io_ok) faults_ |= protocol::FAULT_STATUS_IO;
    if (!in_.adc_ok) faults_ |= protocol::FAULT_ADC;

    if (global_allow_ && !allArmConditionsOk()) {
        setPhysicalGlobalAllow(false);
        state_ = protocol::SupervisorState::RunDisarmed;
    }

    if (state_ == protocol::SupervisorState::BootSafe || state_ == protocol::SupervisorState::SelfTest)
        state_ = protocol::SupervisorState::SafeIdle;
    if (state_ == protocol::SupervisorState::Estop && in_.estop_healthy)
        state_ = protocol::SupervisorState::SafeIdle;
}

protocol::AckResult SafetyManager::requestArm() {
    if (!in_.estop_healthy) return protocol::AckResult::EstopOpen;
    if (!in_.session_valid) return protocol::AckResult::NoSession;
    if (!in_.pi_heartbeat_ok) return protocol::AckResult::HeartbeatStale;
    if (!in_.uart_keepalive_ok) return protocol::AckResult::UartKeepaliveStale;
    if (!in_.pi_buck_pg || !in_.power_fault_clear) return protocol::AckResult::PowerFault;
    if (!in_.control_io_ok || !in_.status_io_ok || !in_.adc_ok) return protocol::AckResult::PeripheralFault;
    if (faults_ != protocol::FAULT_NONE) return protocol::AckResult::UnsafeState;
#if !AUTOMATON_CCB_GLOBAL_SERVO_ALLOW_OUTPUT_ENABLED
    return protocol::AckResult::DevOutputLocked;
#else
    setPhysicalGlobalAllow(true);
    state_ = protocol::SupervisorState::RunArmed;
    return protocol::AckResult::Ok;
#endif
}

void SafetyManager::disarm() {
    setPhysicalGlobalAllow(false);
    if (service_channel_ >= 0) state_ = protocol::SupervisorState::Service;
    else if (in_.estop_healthy) state_ = protocol::SupervisorState::RunDisarmed;
    else state_ = protocol::SupervisorState::Estop;
}

void SafetyManager::enterService(uint8_t channel) {
    setPhysicalGlobalAllow(false);
    service_channel_ = int8_t(channel);
    state_ = protocol::SupervisorState::Service;
}
void SafetyManager::exitService() {
    setPhysicalGlobalAllow(false);
    service_channel_ = -1;
    state_ = in_.estop_healthy ? protocol::SupervisorState::RunDisarmed : protocol::SupervisorState::Estop;
}
void SafetyManager::clearRecoverableFaults(uint32_t mask) {
    if (global_allow_) return;
    faults_ &= ~mask;
}

uint16_t SafetyManager::statusBits() const {
    uint16_t s = 0;
    if (in_.estop_healthy) s |= protocol::STATUS_ESTOP_HEALTHY;
    if (in_.pi_heartbeat_ok) s |= protocol::STATUS_PI_HEARTBEAT_OK;
    if (in_.uart_keepalive_ok) s |= protocol::STATUS_UART_KEEPALIVE_OK;
    if (in_.pi_buck_pg) s |= protocol::STATUS_PI_BUCK_PG;
    if (in_.power_fault_clear) s |= protocol::STATUS_PWR_FAULT_CLEAR;
    if (in_.control_io_ok) s |= protocol::STATUS_CONTROL_IO_OK;
    if (in_.status_io_ok) s |= protocol::STATUS_STATUS_IO_OK;
    if (in_.adc_ok) s |= protocol::STATUS_ADC_OK;
    if (in_.session_valid) s |= protocol::STATUS_SESSION_VALID;
    if (global_allow_) s |= protocol::STATUS_GLOBAL_ALLOW_ASSERTED;
    if (service_channel_ >= 0) s |= protocol::STATUS_SERVICE_ACTIVE;
    return s;
}
}
