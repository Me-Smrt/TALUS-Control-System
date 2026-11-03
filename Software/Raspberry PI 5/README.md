# Raspberry Pi 5 Automaton Host v0.3

The Pi is the high-level orchestrator, but it is not the sole safety layer. The current lower-level software owns two independent communication paths:

1. **SocketCAN** to eight point-to-point RCB channels.
2. **UART + dedicated GPIO heartbeat** to the CCB Safety Supervisor.

## Pi 5 hardware map represented

- SPI0 MOSI/MISO/SCK: BCM10/9/11.
- eight MCP25625 CS: BCM8,7,4,17,27,22,23,24.
- eight MCP25625 INT: BCM25,5,6,12,13,19,16,26.
- Supervisor UART: BCM14/15.
- Supervisor heartbeat: BCM18.
- CCB power-fault input: BCM20.

## Eight CAN channels

`overlays/automaton-ccb-8can-overlay.dts` creates eight `microchip,mcp25625` children on SPI0 using the exact CCB chip-select/interrupt wiring and a 20 MHz controller clock.

Bitrate is deliberately **not** part of the Device Tree. `scripts/configure_can.py` reads `config/automaton.toml` and applies bitrate at runtime using Linux SocketCAN.

The host also derives physical CCB channel number from the sysfs `spi0.<CS>` device path. It does not assume that Linux `can0` is permanently physical channel 0.

## Supervisor link

`automaton/supervisor.py` implements the binary UART protocol and a resynchronizing stream decoder. The independent heartbeat output uses GPIO Zero through `automaton/gpio.py`.

`automaton/hardware_runtime.py` sketches the intended ownership boundary for the eventual main robot process: one control-plane owner should hold the Supervisor session and RCB sessions. Future CV/AI processes must not open competing safety/CAN sessions directly.

## Registry and pairing

The persistent registry treats:

- RCB UID = physical board identity;
- logical role = body function;
- CCB channel = expected physical socket/topology;
- Linux `canX` = diagnostic last-observed name only.

A changed `canX` name by itself is not a remap. A different UID for a role or an unexpected physical CCB channel is a conflict and stays disarmed.

## Install/build notes

- Python >= 3.11.
- Runtime dependencies: `pyserial`, `gpiozero`.
- `pyproject.toml` exposes `automaton-host` when installed as a Python package.
- The included SocketCAN systemd unit assumes deployment beneath `/opt/automaton/Raspberry PI 5`; adjust paths if deployed elsewhere.

The overlay install script requires `dtc` on the Pi and deliberately compiles the `.dts` before installing it.

## Repository bitrate consistency check

Because mismatched CAN bitrates prevent the endpoints from communicating, this cannot be safely negotiated after connection. During development, run:

```bash
python3 scripts/check_repository_config.py
```

It compares `config/automaton.toml` with the RCB PlatformIO `AUTOMATON_CAN_BITRATE` build flag and validates both against the 20 MHz MCP25625 timing model.
