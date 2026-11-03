# Central Control Module Safety Supervisor Firmware v0.3

Target: Arduino Nano R4 / Renesas RA4M1 installed on the CCB Supervisor headers.

## Hardware context represented

- Pi command/status UART through the CCB level shifter.
- Pi heartbeat -> Nano D2.
- `SUPERVISOR_ALLOW_REQ` <- Nano D3.
- shared supervisor I2C interrupt -> D6.
- E-stop sense -> D10, where LOW means closed/healthy.
- A4/A5 supervisor I2C.
- TCA9535 control expander 0x20: `REMOTE_EN_0..7`.
- TCA9535 status expander 0x21: `CAN_ENABLE_0..7` + `REMOTE_PG_0..7`.
- ADS7138 at 0x10: remote-current monitor front end.

## Current safety behavior

`SUPERVISOR_ALLOW_REQ` is forced LOW before other initialization. Global servo authorization requires both the physical E-stop chain and the supervisor request path; Pi software alone cannot bypass that hardware chain.

The draft requires a valid Supervisor session, an independently toggling Pi heartbeat GPIO, UART keepalive, healthy E-stop, Pi power-good, no power fault, and healthy supervisor I2C devices before an arm request could succeed.

Development build locks keep global servo allow and remote high-current power OFF regardless of commands. CAN transceiver enables are intentionally available for communication bring-up.

## Pi protocol

The Pi/Supervisor UART uses a fixed 32-byte frame:

- magic `A5 5A`;
- protocol version;
- message type;
- 16-bit sequence;
- payload length/flags;
- up to 22 payload bytes;
- CRC-16/CCITT-FALSE.

The Pi decoder resynchronizes after noise, partial frames or either endpoint resetting.

## Still bench-gated

- high-current remote eFuse enables;
- global servo authorization output;
- calibrated ADS7138 current conversion/telemetry;
- final current/fault severity policy;
- exact PG timing/fault policy under real remote loads.
