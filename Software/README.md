# Automaton Software / Firmware Draft v0.3

This tree follows the current project layout and the uploaded CCB/RCB hardware:

- `Central Control Module/` — CCB Safety Supervisor firmware (Nano R4).
- `Raspberry PI 5/` — Pi control-plane, SocketCAN, registry/pairing, supervisor UART, deployment helpers.
- `Remote Control Module/` — RCB firmware (Nano R4 + MCP25625 + 2x PCA9685).
- `docs/` — hardware-derived context, bring-up plan, and future compute architecture.

## v0.3 stage boundary

This draft takes the software through the portions that can be designed and statically validated before fabricated-board bench testing. It intentionally stops before enabling physical servo/high-current outputs.

### Implemented in v0.3

**Raspberry Pi 5**

- One custom Device Tree overlay for all 8 MCP25625 devices on shared SPI0.
- Exact CCB CS and INT GPIO map from the uploaded PCB.
- MCP25625 Linux driver binding, 20 MHz controller clock, and active-low level IRQs.
- Runtime SocketCAN bitrate setup (`ip link`); bitrate is not embedded in Device Tree.
- 20 MHz MCP25625 bit-timing compatibility validation before applying a host bitrate.
- Physical channel discovery from `spi0.<chip-select>` sysfs paths instead of assuming `canN == channel N`.
- RCB discovery, HELLO assembly, IDENTIFY pairing, session handling, heartbeat, arm/disarm protocol, normalized servo command format.
- Registry now treats `UID + physical CCB channel` as meaningful identity/topology; Linux netdev names are diagnostic only.
- CCB Supervisor fixed-frame UART protocol with CRC and a resynchronizing stream decoder.
- GPIO Zero adapter for the independent Pi->Supervisor heartbeat on BCM18.
- A `RobotHardwareRuntime` ownership model for future control-plane service integration.
- Configurable TOML deployment settings and a systemd SocketCAN configuration unit.

**RCB**

- Register-level MCP25625 SPI driver.
- Runtime MCP25625 bit-timing calculation from the actual 20 MHz oscillator.
- Classic standard-frame TX/RX using all 3 TX buffers and both RX buffers.
- CAN bus-off/controller-health monitoring and conservative reinitialization.
- Session invalidation after CAN-controller loss; reconnect never rearms motion.
- RA4M1 128-bit silicon unique ID source, reduced to a stable 64-bit protocol fingerprint.
- Persistent logical role storage.
- USB-only high-impedance behavior including SPI/I2C shutdown and release of external bus pins.
- Two-PCA9685 safe startup at 0x40/0x41.
- Deterministic ALL-OFF initialization that does not rely on PCA9685 auto-increment being active at reset.
- 32 local servo profiles, all disabled by default.
- Normalized actuator target format (`-1000..+1000`) rather than raw PCA register access.
- Two-stage arming: precondition validation -> local enable -> bounded bank-PG validation -> ARMED.
- Immediate disarm on lost global allow, stale heartbeat, logic-power loss, PCA loss, bank-PG loss, or CAN-controller failure.

**CCB Supervisor**

- Actual Nano R4 pin map from the uploaded CCB.
- TCA9535 control/status expanders at 0x20/0x21.
- ADS7138 presence check at 0x10.
- Physical E-stop polarity represented as LOW=healthy.
- Independent GPIO heartbeat + UART keepalive/session model.
- Remote-channel CAN enable control and service-state primitives.
- Global servo allow and remote high-current power remain compile-time locked OFF.

## CAN bitrate

CAN bitrate remains configurable, but both ends must use the same value.

- Pi: `Raspberry PI 5/config/automaton.toml` -> `can.bitrate`
- RCB build: `Remote Control Module/platformio.ini` -> `AUTOMATON_CAN_BITRATE`

The host validates that the requested bitrate can be produced from the project's 20 MHz MCP25625 oscillator within the current 0.5% timing-error budget. 125k, 250k, 500k and 1M are exact examples; 800k is intentionally rejected with this oscillator.

The current development default remains **500 kbit/s**. This is a software default, not a frozen project requirement.

Before a development build/deployment, the repository helper can catch an accidental Pi/RCB mismatch:

```bash
python3 "Raspberry PI 5/scripts/check_repository_config.py"
```

## Development locks still ON

These are intentionally not removed in this package:

- RCB `LOCAL_SERVO_ENABLE`: physical assertion compile-locked OFF.
- CCB `SUPERVISOR_ALLOW_REQ` / global servo authorization: compile-locked OFF.
- CCB remote high-current eFuse enables: compile-locked OFF.
- Every RCB servo profile defaults `enabled=false`.
- RA4M1 hardware watchdog integration remains disabled until the Nano R4 upload/bootloader workflow is tested on the real board.

CCB CAN transceiver enables are allowed because enabling communication alone does not energize servo banks.

## Validation performed for this draft

- Pi unit tests: **28/28 passed** in the packaged v0.3 validation run.
- Python `compileall`: passed.
- RCB C++: `-Wall -Wextra -Werror` syntax pass against Arduino/Wire/SPI/EEPROM API stubs.
- CCB C++: same syntax pass against Arduino/Wire API stubs.
- MCP25625 timing search exercised against common bitrates.
- Device Tree source checked by tests for all eight exact CCB CS/INT mappings and active-low level IRQ flags. `dtc` was not installed in the packaging environment, so final overlay compilation remains a Pi bring-up step and the install script compiles-before-install.

These checks do **not** replace:

- compiling against the exact installed Nano R4 core/toolchain;
- compiling/loading the Device Tree overlay on the actual Raspberry Pi OS image;
- oscilloscope/logic-analyzer verification;
- current-limited board bring-up;
- safety-chain bench testing.

See `docs/BUILD_AND_BRINGUP_v0_3.md` for the hardware boundary.

## Documents

- `docs/BUILD_AND_BRINGUP_v0_3.md` — conservative board/software bring-up sequence.
- `docs/PROTOCOL_v0_3.md` — current CAN and Supervisor protocol overview.
- `docs/KNOWN_OPEN_ITEMS_v0_3.md` — deliberate hardware/architecture gates.
- `docs/FUTURE_VISION_AI_ARCHITECTURE.md` — boundary for the next CV + auxiliary AI phase.
- `docs/hardware_context_v0_2.md` — pin/net/address context derived from the uploaded KiCad projects.
