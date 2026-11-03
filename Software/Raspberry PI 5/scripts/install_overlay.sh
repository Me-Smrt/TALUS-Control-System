#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
SRC="$ROOT/overlays/automaton-ccb-8can-overlay.dts"
OUT="/boot/firmware/overlays/automaton-ccb-8can.dtbo"
CONFIG="/boot/firmware/config.txt"

if ! command -v dtc >/dev/null 2>&1; then
  echo "dtc is required (Debian/Raspberry Pi OS package: device-tree-compiler)." >&2
  exit 1
fi

TMP="$(mktemp --suffix=.dtbo)"
trap 'rm -f "$TMP"' EXIT

dtc -@ -I dts -O dtb -o "$TMP" "$SRC"
sudo install -m 0644 "$TMP" "$OUT"

echo "Installed $OUT"
echo
cat <<'TXT'
Add these lines to /boot/firmware/config.txt if they are not already present:

  dtoverlay=automaton-ccb-8can
  dtoverlay=uart0-pi5
  enable_uart=1

Also ensure the Linux serial console is NOT assigned to GPIO14/15, because those pins are the CCB Supervisor UART.
Reboot after changing the boot configuration.
TXT
