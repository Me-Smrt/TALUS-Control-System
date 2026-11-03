#pragma once
#include <stdint.h>
#include <SPI.h>
#include "../protocol/messages.h"

namespace automaton::canbus {

struct BitTiming {
    uint8_t brp = 0;       // register value, actual prescaler = 2*(BRP+1)
    uint8_t prop_seg = 0;  // TQ, 1..8
    uint8_t phase_seg1 = 0;// TQ, 1..8
    uint8_t phase_seg2 = 0;// TQ, 2..8
    uint8_t sjw = 1;       // TQ, 1..4
    uint32_t actual_bitrate = 0;
    uint16_t sample_point_permille = 0;
    uint32_t error_ppm = 0;
};

class CanDriver {
public:
    virtual ~CanDriver() = default;
    virtual bool begin(uint32_t bitrate) = 0;
    virtual void setStandby(bool standby) = 0;
    virtual bool send(const protocol::CanFrame& frame) = 0;
    virtual bool receive(protocol::CanFrame& frame) = 0;
    virtual void service(uint32_t now_ms) = 0;
    virtual bool healthy() const = 0;
};

class Mcp25625Driver final : public CanDriver {
public:
    bool begin(uint32_t bitrate) override;
    void setStandby(bool standby) override;
    bool send(const protocol::CanFrame& frame) override;
    bool receive(protocol::CanFrame& frame) override;
    void service(uint32_t now_ms) override;
    bool healthy() const override { return healthy_; }

    uint8_t errorFlags() const { return error_flags_; }
    uint8_t txErrorCount() const { return tx_error_count_; }
    uint8_t rxErrorCount() const { return rx_error_count_; }
    uint32_t configuredBitrate() const { return configured_bitrate_; }
    const BitTiming& bitTiming() const { return bit_timing_; }

    static bool calculateBitTiming(uint32_t oscillator_hz, uint32_t target_bitrate, BitTiming& out);

private:
    static constexpr uint8_t INSTR_RESET = 0xC0;
    static constexpr uint8_t INSTR_READ = 0x03;
    static constexpr uint8_t INSTR_WRITE = 0x02;
    static constexpr uint8_t INSTR_BIT_MODIFY = 0x05;

    static constexpr uint8_t REG_CANSTAT = 0x0E;
    static constexpr uint8_t REG_CANCTRL = 0x0F;
    static constexpr uint8_t REG_TEC = 0x1C;
    static constexpr uint8_t REG_REC = 0x1D;
    static constexpr uint8_t REG_CNF3 = 0x28;
    static constexpr uint8_t REG_CNF2 = 0x29;
    static constexpr uint8_t REG_CNF1 = 0x2A;
    static constexpr uint8_t REG_CANINTE = 0x2B;
    static constexpr uint8_t REG_CANINTF = 0x2C;
    static constexpr uint8_t REG_EFLG = 0x2D;

    static constexpr uint8_t REG_TXB0CTRL = 0x30;
    static constexpr uint8_t REG_TXB1CTRL = 0x40;
    static constexpr uint8_t REG_TXB2CTRL = 0x50;
    static constexpr uint8_t REG_RXB0CTRL = 0x60;
    static constexpr uint8_t REG_RXB1CTRL = 0x70;

    static constexpr uint8_t MODE_MASK = 0xE0;
    static constexpr uint8_t MODE_NORMAL = 0x00;
    static constexpr uint8_t MODE_CONFIG = 0x80;

    static constexpr uint8_t CANINTF_RX0IF = 0x01;
    static constexpr uint8_t CANINTF_RX1IF = 0x02;
    static constexpr uint8_t EFLG_TXBO = 0x20;
    static constexpr uint8_t TXREQ = 0x08;

    bool configureController(uint32_t bitrate);
    bool requestMode(uint8_t mode);
    void resetController();
    uint8_t readRegister(uint8_t address);
    void readRegisters(uint8_t address, uint8_t* data, uint8_t length);
    void writeRegister(uint8_t address, uint8_t value);
    void writeRegisters(uint8_t address, const uint8_t* data, uint8_t length);
    void bitModify(uint8_t address, uint8_t mask, uint8_t value);
    bool loadTxBuffer(uint8_t ctrl_reg, const protocol::CanFrame& frame);
    bool readRxBuffer(uint8_t ctrl_reg, protocol::CanFrame& frame);
    void beginTransaction();
    void endTransaction();

    bool healthy_ = false;
    bool standby_ = true;
    uint8_t error_flags_ = 0;
    uint8_t tx_error_count_ = 0;
    uint8_t rx_error_count_ = 0;
    uint32_t configured_bitrate_ = 0;
    uint32_t last_health_poll_ms_ = 0;
    BitTiming bit_timing_{};
    SPISettings spi_settings_{8000000, MSBFIRST, SPI_MODE0};
};

}  // namespace automaton::canbus
