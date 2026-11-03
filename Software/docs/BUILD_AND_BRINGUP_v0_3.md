# Automaton Software/Firmware v0.3 — Build and Bring-Up Guide

This guide is deliberately conservative. v0.3 contains enough real hardware-facing code to begin board bring-up, but all high-energy actuator paths remain development-locked.

## 1. Safety state of this release

Keep these build-time locks at their v0.3 values during initial bring-up:

### RCB

```ini
-DAUTOMATON_PHYSICAL_SERVO_OUTPUTS_ENABLED=0
-DAUTOMATON_HARDWARE_WATCHDOG_ENABLED=0
```

### CCB

```ini
-DAUTOMATON_CCB_GLOBAL_SERVO_ALLOW_OUTPUT_ENABLED=0
-DAUTOMATON_CCB_REMOTE_POWER_OUTPUTS_ENABLED=0
-DAUTOMATON_CCB_CAN_CHANNEL_ENABLE_OUTPUTS_ENABLED=1
```

With those values:

- RCB firmware cannot assert `LOCAL_SERVO_ENABLE`.
- CCB Supervisor firmware cannot assert the global servo-allow request.
- CCB Supervisor firmware cannot turn on remote high-current channel power.
- CAN transceivers may be enabled for communications testing.
- Every RCB servo profile is disabled by default.

Do not remove those locks merely because compilation succeeds. Remove them one subsystem at a time only after the associated hardware test is complete.

## 2. CAN bitrate — configurable, but matched at both ends

The bitrate is intentionally not frozen.

Pi configuration:

```toml
# Raspberry PI 5/config/automaton.toml
[can]
bitrate = 500000
```

RCB build configuration:

```ini
# Remote Control Module/platformio.ini
-DAUTOMATON_CAN_BITRATE=500000UL
```

The RCB computes MCP25625 timing from the 20 MHz oscillator at boot. The Pi validates the same 20 MHz timing model before applying a SocketCAN bitrate.

The two values must match. The default of 500 kbit/s is only a development default.

Current timing search gives exact solutions for common values including 125 kbit/s, 250 kbit/s, 500 kbit/s, and 1 Mbit/s. A requested value outside the timing-error limit is rejected instead of silently approximated.

## 3. Build the Nano R4 firmware

Both Nano R4 firmware projects include PlatformIO environments using board ID `nano_r4`.

From the repository root:

```bash
cd "Software/Remote Control Module"
pio run

cd "../Central Control Module"
pio run
```

Upload only after checking the compile-time safety flags in each `platformio.ini`.

For the first RCB firmware upload, leave servo-bank/high-current power physically disconnected where practical. USB-only firmware behavior can be checked before external `5V_LOGIC` is present.

## 4. RCB first-board checks

### 4.1 USB-only check

Power the Nano R4 from USB while the RCB external logic rail is off.

Expected behavior:

- `LOCAL_SERVO_ENABLE` remains inactive.
- MCP25625/PCA9685 initialization does not run.
- SPI/I2C/control pins connected to unpowered external ICs are released to high impedance where practical.
- no servo bank can energize.

Verify with a multimeter before relying on firmware behavior alone.

### 4.2 External 5V logic check

Apply only the board's required logic supply using a current-limited source.

Verify:

- `LOGIC_PWR_SENSE` crosses the firmware threshold reliably;
- both PCA9685 devices ACK at 0x40 and 0x41;
- MCP25625 initializes over SPI;
- CAN transceiver leaves standby only after controller setup;
- `LOCAL_SERVO_ENABLE` remains inactive because the v0.3 output lock is still compiled in.

### 4.3 RCB CAN loop

Connect one RCB to one known CCB CAN channel.

Before using all eight channels, verify one channel with:

```bash
ip -details link show can0
candump can0
```

The RCB should emit its four-part HELLO while unassociated with a host session and should enter a session only after a `SESSION_BEGIN` from the Pi.

Unplug/reconnect the CAN path and verify that no prior arming/session state is restored.

## 5. Raspberry Pi 5 Device Tree and SocketCAN

### 5.1 Install the eight-channel overlay

On the Pi:

```bash
cd "Software/Raspberry PI 5"
sudo apt install device-tree-compiler
sudo ./scripts/install_overlay.sh
```

The script compiles the source before installation. It installs:

```text
/boot/firmware/overlays/automaton-ccb-8can.dtbo
```

Then ensure `/boot/firmware/config.txt` contains the required overlay/UART lines printed by the installer and reboot.

The Linux serial console must not own GPIO14/15 because those pins belong to the CCB Supervisor UART.

### 5.2 Confirm all eight physical CAN devices

After reboot:

```bash
ip -details link show type can
python3 scripts/configure_can.py --config config/automaton.toml
python3 -m automaton.cli --config config/automaton.toml topology
```

The topology command resolves physical CCB channel from the SPI device path rather than trusting `canN` numbering.

Expected mapping is based on the PCB chip-select wiring:

| Physical CCB channel | SPI CS GPIO | CAN INT GPIO |
|---:|---:|---:|
| 0 | BCM8  | BCM25 |
| 1 | BCM7  | BCM5  |
| 2 | BCM4  | BCM6  |
| 3 | BCM17 | BCM12 |
| 4 | BCM27 | BCM13 |
| 5 | BCM22 | BCM19 |
| 6 | BCM23 | BCM16 |
| 7 | BCM24 | BCM26 |

Linux may choose different `canN` names; that does not change physical CCB channel identity.

## 6. Pi Python environment

Recommended development install:

```bash
cd "Software/Raspberry PI 5"
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest -q
```

For a deployment copy, place the TOML configuration at:

```text
/etc/automaton/automaton.toml
```

and create:

```text
/var/lib/automaton/
/var/log/automaton/
```

with ownership appropriate for the eventual robot-control service account.

## 7. CCB Supervisor bring-up

Start with high-current remote power and global servo permission locked off.

Verify, in order:

1. Nano R4 boots with `SUPERVISOR_ALLOW_REQ` inactive.
2. E-stop sensing reports **LOW = loop closed/healthy** and HIGH = open/stop.
3. TCA9535 at 0x20 is reachable.
4. TCA9535 at 0x21 is reachable.
5. ADS7138 at 0x10 is reachable.
6. Pi GPIO18 heartbeat transitions are seen by the Supervisor.
7. Pi UART session/keepalive is accepted on D0/D1.
8. CAN channel-enable outputs can be changed without enabling remote high-current power.
9. Loss of either heartbeat path causes the supervisor to fall to a non-armed state.

The ADS7138 path is currently a presence/protocol scaffold. Current calibration and fault thresholds are intentionally deferred until measurements from the fabricated CCB are available.

## 8. Identity and pairing test

With communications working and the node disarmed:

```bash
automaton-host --config /etc/automaton/automaton.toml discover
automaton-host --config /etc/automaton/automaton.toml pair HEAD
```

Press the physical IDENTIFY button on the intended RCB.

The host records:

- logical role;
- RCB UID fingerprint;
- expected physical CCB channel;
- last-observed Linux CAN interface.

A changed Linux interface name alone is not a conflict. A different UID or unexpected physical CCB channel is.

## 9. Servo/PCA bench sequence — only after communications pass

v0.3 already implements the safe PCA layer, but actuator output remains locked. When the project is ready for a later unlock:

1. Keep the CCB global allow path locked off initially.
2. Test one RCB with a current-limited bench supply.
3. Populate a single servo profile with measured pulse limits.
4. Unlock the RCB local-enable output only for the controlled test build.
5. Exercise the two-stage ARM transition and verify PG timeout behavior.
6. Verify hardware OE disables PWM immediately on global/local permission loss.
7. Test one servo with conservative pulse limits.
8. Test one power bank at a time.
9. Only then test multiple banks and coordinated motion.

Never use the generic `-1000..+1000` motion range as proof that a particular mechanism is mechanically safe. Each actuator still needs calibration and mechanical limits.

## 10. Hardware watchdog

The RA4M1 hardware watchdog abstraction is intentionally not enabled in v0.3. The desired behavior remains:

```text
firmware stalls -> watchdog reset -> LOCAL_SERVO_ENABLE defaults inactive -> boot disarmed
```

Enable and test it only after verifying the exact Nano R4 core/bootloader/upload workflow on the real board. Watchdog reset must never restore an armed state.

## 11. What counts as a successful v0.3 bring-up

Before removing any high-energy development lock, the following should all be repeatable:

- all eight Pi MCP25625 devices enumerate;
- physical channel topology is correct;
- configured CAN bitrate is stable;
- one and then multiple RCBs HELLO reliably;
- RCB UID and role persist across reset;
- IDENTIFY pairing works;
- duplicate/mismatched registry assignments are rejected;
- heartbeat loss disarms;
- CAN disconnect/reconnect does not auto-rearm;
- Supervisor heartbeat loss and E-stop transitions revoke permission;
- USB-only mode does not back-power external RCB logic;
- PCA devices always start with outputs logically OFF;
- all observed failures fall toward a disarmed state.

At that point the next robotics-software stage is calibrated actuator motion. Computer vision can be developed in parallel because it will sit above the hardware-control boundary described in `FUTURE_VISION_AI_ARCHITECTURE.md`.
