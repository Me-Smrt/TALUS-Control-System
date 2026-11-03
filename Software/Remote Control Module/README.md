# Remote Control Module Firmware v0.3

Target: Arduino Nano R4 / Renesas RA4M1 on the current RCB hardware.

## Modules

- `board/` — frozen current pin map and software tuning values.
- `can/` — MCP25625 SPI driver and bit timing.
- `protocol/` — Classic CAN application protocol.
- `identity/` — RA4M1 silicon UID + persistent role/config.
- `safety/` — sole owner of `LOCAL_SERVO_ENABLE`, communication watchdog, two-stage arm state.
- `servo/` — safe dual-PCA9685 driver and local servo profiles.
- `diagnostics/` — identify button and status LED.

## CAN configuration

The MCP25625 is configured from the actual 20 MHz RCB oscillator. `AUTOMATON_CAN_BITRATE` is supplied as a build flag in `platformio.ini`; change it together with the Pi's TOML bitrate.

The driver:

- configures standard 11-bit Classic CAN;
- uses 8 MHz SPI;
- accepts protocol traffic on both receive buffers;
- uses all three hardware TX buffers without blocking;
- polls EFLG/TEC/REC/controller mode;
- places the integrated transceiver in standby on controller failure/bus-off;
- retries controller initialization conservatively;
- invalidates the host session after CAN failure so reconnection cannot restore movement.

## Servo behavior

Both PCA9685 devices are initialized with hardware OE already disabled by the independent RCB authorization chain. All PWM channels are explicitly forced FULL-OFF before commands are accepted.

All 32 `ServoProfile` entries default to `enabled=false`. A host command is a normalized local goal in `[-1000,+1000]`; the RCB maps that through a validated profile to a pulse width. The protocol never exposes raw PCA9685 register writes.

Physical servo authorization remains compile-time locked off (`AUTOMATON_PHYSICAL_SERVO_OUTPUTS_ENABLED=0`).

## Arming sequence once the development lock is eventually removed

1. Verify external logic power.
2. Verify CAN controller and a fresh host session/heartbeat.
3. Verify physical global allow.
4. Verify both PCA9685 devices.
5. Verify role/configuration.
6. Verify no active critical fault.
7. Assert `LOCAL_SERVO_ENABLE`.
8. Enter `ARMING_WAIT_POWER_GOOD`.
9. Require all four bank PG inputs within the configured startup window.
10. Only then enter `ARMED`.

Failure at any point falls back to local enable LOW.

## USB-only mode

When A7 indicates external `5V_LOGIC` is absent, the firmware does not initialize external peripherals. If external logic disappears after startup, it ends SPI/I2C and releases SCK/MOSI/MISO, CAN CS/INT/STBY and SDA/SCL as inputs to avoid parasitic powering.

## UID

Production Nano R4 builds use the RA4M1 128-bit silicon unique ID from `R_BSP_UniqueIdGet()`. Protocol v1 currently carries a deterministic 64-bit FNV-1a fingerprint of all 128 bits; the full hardware UID remains the source identity.

## Still bench-gated

- physical servo-enable output;
- real servo calibration profiles;
- final bank-PG startup timing;
- analog logic-power thresholds;
- RA4M1 hardware watchdog enabling/toolchain behavior;
- actual servo/load transient behavior.
