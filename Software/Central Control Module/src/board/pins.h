#pragma once
#include <Arduino.h>

namespace automaton::ccb::pins {
// Nano R4 digital header mapping confirmed from the CCB PCB netlist.
constexpr uint8_t PI_HEARTBEAT = 2;          // D2 <- PI_HEARTBEAT_5V
constexpr uint8_t SUPERVISOR_ALLOW_REQ = 3; // D3 -> hardware E-stop/global-allow gate
constexpr uint8_t SUP_IO_INT_N = 6;          // D6 <- shared TCA9535/ADS7138 interrupt
constexpr uint8_t CCB_RGB_DATA = 7;          // D7 -> status RGB data
constexpr uint8_t PWR_FAULT_N = 8;           // D8 <- active-low CCB power fault
constexpr uint8_t PI_BUCK_PG = 9;            // D9 <- Pi 5 V buck power-good
constexpr uint8_t ESTOP_SENSE = 10;          // D10 <- LOW healthy, HIGH E-stop/open loop
constexpr uint8_t CCB_FAULT_LED = 11;         // D11 -> fault LED

constexpr uint8_t I2C_SDA_PIN = A4;
constexpr uint8_t I2C_SCL_PIN = A5;

// D0/D1 are used by Serial1 for Pi <-> Supervisor UART.
constexpr uint8_t SUP_UART_RX = 0;
constexpr uint8_t SUP_UART_TX = 1;
}
