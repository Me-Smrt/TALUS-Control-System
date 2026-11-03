#include "safety_manager.h"
#include "../board/pins.h"
#include "../board/board_config.h"
#include <Arduino.h>

namespace automaton::safety {

void SafetyManager::forceLocalEnable(bool enabled) {
#if AUTOMATON_PHYSICAL_SERVO_OUTPUTS_ENABLED
    local_enable_ = enabled;
#else
    local_enable_ = false;
    (void)enabled;
#endif
    pinMode(pins::LOCAL_SERVO_ENABLE, OUTPUT);
    digitalWrite(pins::LOCAL_SERVO_ENABLE, local_enable_ ? HIGH : LOW);
}

void SafetyManager::begin() {
    forceLocalEnable(false);
    state_ = protocol::RcbState::SafeBoot;
}

bool SafetyManager::allBanksPowerGood() const {
    for (bool pg : in_.bank_pg) if (!pg) return false;
    return true;
}

void SafetyManager::setMissingBankFaults() {
    if (!in_.bank_pg[0]) faults_ |= protocol::FAULT_BANK_A_PG;
    if (!in_.bank_pg[1]) faults_ |= protocol::FAULT_BANK_B_PG;
    if (!in_.bank_pg[2]) faults_ |= protocol::FAULT_BANK_C_PG;
    if (!in_.bank_pg[3]) faults_ |= protocol::FAULT_BANK_D_PG;
}

void SafetyManager::updateInputs(const SafetyInputs& in) {
    const bool had_global = in_.global_allow;
    const bool had_logic = in_.logic_power_ok;
    const bool had_pca0 = in_.pca0_present;
    const bool had_pca1 = in_.pca1_present;
    const bool was_actuating = local_enable_;
    in_ = in;

    if (had_global && !in_.global_allow && was_actuating) {
        // Loss of the supervisor's global permission is an immediate disarm event, but
        // GLOBAL_ALLOW can also be intentionally revoked during a normal system disarm.
        // Keep the diagnostic bit while permission is absent, then clear it on recovery;
        // explicit ARM is still required, so recovery can never resume motion by itself.
        setFault(protocol::FAULT_GLOBAL_ALLOW_LOST);
        disarm(protocol::DisarmReason::GlobalAllowLost);
    }
    if (!had_global && in_.global_allow) {
        clearFault(protocol::FAULT_GLOBAL_ALLOW_LOST);
    }
    if (had_logic && !in_.logic_power_ok) {
        setFault(protocol::FAULT_LOGIC_POWER);
        disarm(protocol::DisarmReason::LogicPowerLost);
    }
    if (was_actuating && had_pca0 && !in_.pca0_present) {
        setFault(protocol::FAULT_PCA0_MISSING);
        disarm(protocol::DisarmReason::PeripheralLost);
    }
    if (was_actuating && had_pca1 && !in_.pca1_present) {
        setFault(protocol::FAULT_PCA1_MISSING);
        disarm(protocol::DisarmReason::PeripheralLost);
    }
    if (state_ == protocol::RcbState::Armed && !allBanksPowerGood()) {
        setMissingBankFaults();
        disarm(protocol::DisarmReason::BankPowerGoodLost);
    }
}

bool SafetyManager::sessionFresh(uint32_t now_ms) const {
    return heartbeat_seen_ && (uint32_t(now_ms - last_heartbeat_ms_) <= board::HEARTBEAT_TIMEOUT_MS);
}

void SafetyManager::noteHeartbeat(uint32_t now_ms) {
    heartbeat_seen_ = true;
    last_heartbeat_ms_ = now_ms;
    clearFault(protocol::FAULT_CAN_TIMEOUT);
}

void SafetyManager::tick(uint32_t now_ms) {
    if (heartbeat_seen_ && uint32_t(now_ms - last_heartbeat_ms_) > board::HEARTBEAT_TIMEOUT_MS) {
        setFault(protocol::FAULT_CAN_TIMEOUT);
        disarm(protocol::DisarmReason::HeartbeatTimeout);
        heartbeat_seen_ = false;
    }

    if (state_ == protocol::RcbState::ArmingWaitPowerGood && local_enable_) {
        if (allBanksPowerGood()) {
            state_ = protocol::RcbState::Armed;
        } else if (uint32_t(now_ms - arm_started_ms_) > board::BANK_PG_STARTUP_TIMEOUT_MS) {
            setMissingBankFaults();
            disarm(protocol::DisarmReason::Fault);
        }
    }
}

protocol::AckResult SafetyManager::requestArm(uint32_t now_ms) {
#if !AUTOMATON_PHYSICAL_SERVO_OUTPUTS_ENABLED
    (void)now_ms;
    forceLocalEnable(false);
    return protocol::AckResult::DevOutputLocked;
#else
    if (!in_.logic_power_ok) return protocol::AckResult::LogicPowerMissing;
    if (!in_.can_ok || !sessionFresh(now_ms)) return protocol::AckResult::CanStale;
    if (!in_.session_valid) return protocol::AckResult::NoSession;
    if (!in_.global_allow) return protocol::AckResult::GlobalAllowMissing;
    if (!in_.pca0_present || !in_.pca1_present) return protocol::AckResult::PcaMissing;
    if (!in_.config_valid) return protocol::AckResult::ConfigInvalid;
    if (faults_ != protocol::FAULT_NONE) return protocol::AckResult::FaultActive;

    // Bank PG cannot be required before LOCAL_SERVO_ENABLE because the bank regulators
    // are downstream of SERVO_MASTER_ALLOW. Enter a bounded arming state, then validate PG.
    forceLocalEnable(true);
    arm_started_ms_ = now_ms;
    state_ = protocol::RcbState::ArmingWaitPowerGood;
    return protocol::AckResult::ArmPending;
#endif
}

void SafetyManager::disarm(protocol::DisarmReason) {
    forceLocalEnable(false);
    if (state_ != protocol::RcbState::UsbOnly && state_ != protocol::RcbState::Initializing)
        state_ = protocol::RcbState::ReadyDisarmed;
}

uint16_t SafetyManager::statusBits() const {
    uint16_t s = 0;
    if (in_.logic_power_ok) s |= protocol::STATUS_LOGIC_POWER_OK;
    if (in_.can_ok) s |= protocol::STATUS_CAN_OK;
    if (in_.global_allow) s |= protocol::STATUS_GLOBAL_ALLOW;
    if (local_enable_) s |= protocol::STATUS_LOCAL_ENABLE;
    if (local_enable_ && in_.global_allow) s |= protocol::STATUS_SERVO_MASTER;
    if (in_.bank_pg[0]) s |= protocol::STATUS_BANK_A_PG;
    if (in_.bank_pg[1]) s |= protocol::STATUS_BANK_B_PG;
    if (in_.bank_pg[2]) s |= protocol::STATUS_BANK_C_PG;
    if (in_.bank_pg[3]) s |= protocol::STATUS_BANK_D_PG;
    if (in_.pca0_present) s |= protocol::STATUS_PCA0_PRESENT;
    if (in_.pca1_present) s |= protocol::STATUS_PCA1_PRESENT;
    if (in_.config_valid) s |= protocol::STATUS_PAIRED;
    if (in_.session_valid) s |= protocol::STATUS_SESSION_VALID;
    if (state_ == protocol::RcbState::Armed && local_enable_) s |= protocol::STATUS_ARMED;
    if (state_ == protocol::RcbState::ArmingWaitPowerGood && local_enable_) s |= protocol::STATUS_ARMING;
    return s;
}

}  // namespace automaton::safety
