#pragma once
#include <stdint.h>

namespace automaton::ccb::board {
constexpr uint8_t SUPERVISOR_PROTOCOL_VERSION = 1;
constexpr uint8_t HARDWARE_REVISION = 1; // Placeholder until the fabricated CCB revision identifier is frozen.
constexpr uint8_t FW_MAJOR = 0;
constexpr uint8_t FW_MINOR = 3;
constexpr uint8_t FW_PATCH = 0;

constexpr uint32_t DEBUG_BAUD = 115200;
constexpr uint32_t PI_UART_BAUD = 115200;
constexpr uint32_t I2C_CLOCK_HZ = 400000;

constexpr uint8_t TCA_CONTROL_ADDR = 0x20;
constexpr uint8_t TCA_STATUS_ADDR = 0x21;
constexpr uint8_t ADS7138_ADDR = 0x10;

// Draft timing values. Keep configurable until tested on hardware.
constexpr uint32_t PI_HEARTBEAT_TIMEOUT_MS = 500;
constexpr uint32_t UART_KEEPALIVE_TIMEOUT_MS = 750;
constexpr uint32_t STATUS_INTERVAL_MS = 250;
constexpr uint32_t HELLO_INTERVAL_MS = 2000;

// Development locks. Global servo permission and remote high-current power stay disabled
// until bench validation explicitly enables them.
#ifndef AUTOMATON_CCB_GLOBAL_SERVO_ALLOW_OUTPUT_ENABLED
#define AUTOMATON_CCB_GLOBAL_SERVO_ALLOW_OUTPUT_ENABLED 0
#endif

#ifndef AUTOMATON_CCB_REMOTE_POWER_OUTPUTS_ENABLED
#define AUTOMATON_CCB_REMOTE_POWER_OUTPUTS_ENABLED 0
#endif

#ifndef AUTOMATON_CCB_CAN_CHANNEL_ENABLE_OUTPUTS_ENABLED
#define AUTOMATON_CCB_CAN_CHANNEL_ENABLE_OUTPUTS_ENABLED 1
#endif
}
