#pragma once
#include <Arduino.h>

namespace automaton::pins {
constexpr uint8_t SPI_SCK_PIN = 13;
constexpr uint8_t SPI_MOSI_PIN = 11;
constexpr uint8_t SPI_MISO_PIN = 12;
constexpr uint8_t CAN_CS_N = 10;
constexpr uint8_t CAN_INT_N = 2;
constexpr uint8_t CAN_STBY = 6;

constexpr uint8_t LOCAL_SERVO_ENABLE = 7;
constexpr uint8_t GLOBAL_SERVO_ALLOW_OK = 8;
constexpr uint8_t RCB_IDENTIFY_N = 3;
constexpr uint8_t RCB_STATUS_LED = 9;

constexpr uint8_t BANK_A_PG = A0;
constexpr uint8_t BANK_B_PG = A1;
constexpr uint8_t BANK_C_PG = A2;
constexpr uint8_t BANK_D_PG = A3;
constexpr uint8_t I2C_SDA_PIN = A4;
constexpr uint8_t I2C_SCL_PIN = A5;
constexpr uint8_t LOGIC_PWR_SENSE = A7;

constexpr uint8_t DEBUG_TX = 1;
constexpr uint8_t DEBUG_RX = 0;
}
