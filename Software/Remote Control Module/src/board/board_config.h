#pragma once
#include <stdint.h>

namespace automaton::board {
constexpr uint8_t PROTOCOL_VERSION = 1;
constexpr uint8_t CONFIG_VERSION = 1;
constexpr uint8_t HARDWARE_REVISION = 1;  // Placeholder until the fabricated PCB revision ID is frozen.
constexpr uint8_t FW_MAJOR = 0;
constexpr uint8_t FW_MINOR = 3;
constexpr uint8_t FW_PATCH = 0;

constexpr uint8_t PWM_CHANNEL_COUNT = 32;
constexpr uint8_t BANK_COUNT = 4;
constexpr uint8_t SUPPORTED_BANK_MASK = 0x0F;

// Physical values confirmed from the uploaded RCB hardware.
constexpr uint32_t MCP25625_OSC_HZ = 20000000;
constexpr uint32_t CAN_SPI_HZ = 8000000;
constexpr uint8_t PCA0_ADDRESS = 0x40;
constexpr uint8_t PCA1_ADDRESS = 0x41;

// Software tuning values. CAN bitrate deliberately remains configurable.
#ifndef AUTOMATON_CAN_BITRATE
#define AUTOMATON_CAN_BITRATE 500000UL
#endif
constexpr uint32_t CAN_BITRATE = AUTOMATON_CAN_BITRATE;
constexpr uint32_t I2C_CLOCK_HZ = 400000;
constexpr uint32_t PCA9685_OSC_HZ = 25000000;
constexpr float SERVO_PWM_HZ = 50.0f;

constexpr uint32_t HEARTBEAT_TIMEOUT_MS = 500;
constexpr uint32_t STATUS_INTERVAL_MS = 500;
constexpr uint32_t HELLO_RETRY_MS = 2000;
constexpr uint32_t CAN_REINIT_INTERVAL_MS = 2000;
constexpr uint32_t BANK_PG_STARTUP_TIMEOUT_MS = 250;
constexpr uint32_t IDENTIFY_DEBOUNCE_MS = 30;
constexpr uint32_t IDENTIFY_LONG_PRESS_MS = 3000;

// Absolute firmware-side pulse envelope. Individual servo profiles must be narrower.
constexpr uint16_t ABS_MIN_SERVO_PULSE_US = 500;
constexpr uint16_t ABS_MAX_SERVO_PULSE_US = 2500;

// Arduino analogReadResolution(12) => 0..4095. With a nominal 5 V ADC range,
// the 5V_LOGIC / 2 divider reads ~2.5 V (~2048 counts). Measure these on hardware later.
constexpr uint16_t LOGIC_PWR_PRESENT_THRESHOLD = 1500;
constexpr uint16_t LOGIC_PWR_LOST_THRESHOLD = 1200;

// Development lock: no physical servo-power request until explicit bench validation.
#ifndef AUTOMATON_PHYSICAL_SERVO_OUTPUTS_ENABLED
#define AUTOMATON_PHYSICAL_SERVO_OUTPUTS_ENABLED 0
#endif

// The Arduino Renesas WDT library currently has an open Nano R4 upload interaction issue.
// Keep this disabled until the toolchain/bootloader workflow is bench-verified.
#ifndef AUTOMATON_HARDWARE_WATCHDOG_ENABLED
#define AUTOMATON_HARDWARE_WATCHDOG_ENABLED 0
#endif
}
