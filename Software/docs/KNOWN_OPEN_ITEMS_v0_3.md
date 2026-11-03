# Known Open Items at the v0.3 Boundary

These are intentionally **not** presented as bugs that should be guessed around in software. Most require hardware measurements or a later architecture decision.

## Hardware/bench-gated

- Compile and upload both Nano R4 projects with the exact installed Arduino/PlatformIO core.
- Compile/load the Pi Device Tree overlay on the actual Raspberry Pi OS image.
- Verify all 8 MCP25625 channels electrically and confirm IRQ behavior under load.
- Verify the RCB 20 MHz MCP25625 timing with a real CAN analyzer.
- Determine final CAN bitrate; it remains configurable.
- Measure `LOGIC_PWR_SENSE` thresholds/noise on the fabricated RCB.
- Measure servo-bank PG assertion/deassertion timing and set the final timeout.
- Calibrate ADS7138 current conversion/thresholds from the final CCB analog front end.
- Verify CCB E-stop/supervisor/global-allow chain electrically.
- Validate USB-only no-back-power behavior with actual board leakage measurements.
- Validate PCA9685 oscillator tolerance and actual servo frequency if precision matters.
- Validate RA4M1 hardware-watchdog/bootloader/upload workflow before enabling it.
- Freeze explicit CCB/RCB hardware-revision identifiers; firmware currently reports revision `1` as a development placeholder.

## Actuator configuration

- Define servo profiles per physical actuator.
- Measure per-servo minimum/neutral/maximum pulse widths.
- Define mechanical position limits.
- Define inversion/direction.
- Define local speed/acceleration limits.
- Decide interpolation/trajectory policy.
- Define per-bank population and whether every PG input is always required for every RCB role.

## CCB policy

- Final global ARM policy and fault severity/latching categories.
- Final service-mode timing and remote-power sequencing based on bench measurements.
- Remote-current warning/trip thresholds.
- Final behavior for recoverable versus latching Supervisor faults.

## Host/control architecture

- Permanent robot-control daemon/API.
- IPC contract for CV, behavior, UI, and auxiliary AI services.
- Configuration schema for full logical actuator mapping.
- Structured persistent event-log format/rotation.
- Firmware update strategy/bootloader policy.
- User-facing commissioning/service UI.

## Future CV/AI

- camera(s) and interface;
- detection/tracking stack;
- Jetson-class auxiliary computer choice;
- local LLM;
- STT/TTS engines;
- Pi<->auxiliary RPC/message transport;
- behavior/planning layer that converts perception/AI intent to validated robot actions.

See `FUTURE_VISION_AI_ARCHITECTURE.md` for the intended safety boundary before those choices are made.
