# Hardware Context Captured from the Uploaded CCB/RCB Projects

This document is a software-facing extraction of the current KiCad projects. It is intended to keep firmware constants aligned with the physical boards.

## RCB Nano R4

- D13: MCP25625 SCK
- D12: MCP25625 MISO
- D11: MCP25625 MOSI
- D10: MCP25625 CS_N
- D9: status LED
- D8: GLOBAL_SERVO_ALLOW_OK input
- D7: LOCAL_SERVO_ENABLE output
- D6: MCP25625 STBY
- D3: IDENTIFY_N
- D2: MCP25625 INT_N
- D1/D0: debug UART TX/RX
- A0..A3: servo bank PG A..D
- A4/A5: PCA9685 I2C
- A7: 5V_LOGIC divider sense
- MCP25625 oscillator: 20 MHz
- PCA9685 addresses: 0x40 and 0x41

## CCB Supervisor Nano R4

Derived from the actual connector pad nets and the Nano R4 header ordering:

- D1 TX -> SUP_UART_TX_5V -> Pi UART RX
- D0 RX <- SUP_UART_RX_5V <- Pi UART TX
- D2 <- PI_HEARTBEAT_5V
- D3 -> SUPERVISOR_ALLOW_REQ
- D6 <- SUP_IO_INT_N
- D7 -> CCB_RGB_DATA
- D8 <- PWR_FAULT_N
- D9 <- PI_BUCK_PG
- D10 <- ESTOP_SENSE
- D11 -> CCB_FAULT_LED
- A4/A5 -> SUP_I2C_SDA/SCL

`ESTOP_SENSE` is pulled up to SUP_5V and the external E-stop loop shorts it to ground when healthy. Therefore:

- LOW = closed/healthy loop
- HIGH = open loop / E-stop condition

The physical global-allow gate is fail-safe: a pull-up holds the P-channel switch off unless the Nano actively requests allow and the E-stop transistor path is simultaneously able to pull the gate low.

## CCB Pi 40-pin header

- physical 8 / GPIO14: PI_SUP_UART_TX_3V3
- physical 10 / GPIO15: PI_SUP_UART_RX_3V3
- physical 12 / GPIO18: PI_HEARTBEAT_3V3
- physical 19 / GPIO10: SPI MOSI
- physical 21 / GPIO9: SPI MISO
- physical 23 / GPIO11: SPI SCK
- physical 24 / GPIO8: CS0_N
- physical 26 / GPIO7: CS1_N
- physical 7 / GPIO4: CS2_N
- physical 11 / GPIO17: CS3_N
- physical 13 / GPIO27: CS4_N
- physical 15 / GPIO22: CS5_N
- physical 16 / GPIO23: CS6_N
- physical 18 / GPIO24: CS7_N
- physical 22 / GPIO25: INT0_N
- physical 29 / GPIO5: INT1_N
- physical 31 / GPIO6: INT2_N
- physical 32 / GPIO12: INT3_N
- physical 33 / GPIO13: INT4_N
- physical 35 / GPIO19: INT5_N
- physical 36 / GPIO16: INT6_N
- physical 37 / GPIO26: INT7_N
- physical 38 / GPIO20: PWR_FAULT_N

## CCB I2C devices

- U6 TCA9535 `SUP_IO_CONTROL`: 0x20
  - port 0 P00..P07: REMOTE_EN_0..7
  - port 1 physically unused
- U7 TCA9535 `SUP_IO_STATUS`: 0x21
  - port 0 P00..P07: CAN_ENABLE_0..7
  - port 1 P10..P17: REMOTE_PG_0..7
- U18 ADS7138: 0x10 with the current DNP/DNP ADDR strap
  - AIN0..AIN7: REMOTE_IMON_0..7

All three devices share `SUP_IO_INT_N` where applicable. The TCA9535 limits the shared I2C bus to 400 kHz.

## CCB CAN channels

Eight MCP25625 devices share Pi SPI and each has a dedicated CS and INT line. Every controller uses a 20 MHz crystal. Each channel's STBY input is pulled HIGH by default and a supervisor-controlled 2N7002 pulls it LOW when `CAN_ENABLE_X` is asserted, so power-up defaults to CAN standby.

The Linux kernel `mcp251x` device-tree binding supports `microchip,mcp25625`, making SocketCAN exposure the preferred Pi architecture rather than implementing the CCB CAN controllers in userspace.
