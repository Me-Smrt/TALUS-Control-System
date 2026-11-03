#!/usr/bin/env python3
from __future__ import annotations
import argparse
import sys
from pathlib import Path

# Allow this checkout to run directly before it is packaged/installed as a Python module.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from automaton.settings import load_settings
from automaton.can_setup import configure_all, list_states
from automaton.can_topology import discover_ccb_channels, ordered_interfaces


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", type=Path, default=Path("/etc/automaton/automaton.toml"))
    ap.add_argument("--bitrate", type=int, help="override configured CAN bitrate")
    ap.add_argument("--allow-missing", action="store_true")
    args = ap.parse_args()

    settings = load_settings(args.config)
    bitrate = args.bitrate or settings.can.bitrate

    if settings.can.auto_discover_by_spi:
        mapping = discover_ccb_channels()
        names = ordered_interfaces(mapping, require_all=not args.allow_missing)
        if mapping:
            print("Physical CCB CAN topology: " + ", ".join(f"ch{ch}={name}" for ch, name in sorted(mapping.items())))
    else:
        names = settings.can.interfaces

    configured = configure_all(
        names, bitrate, settings.can.restart_ms,
        require_all=not args.allow_missing,
    )
    print(f"Configured {len(configured)} CAN interface(s) at {bitrate} bit/s: {', '.join(configured)}")
    for state in list_states(names):
        print(f"{state.name}: {'present' if state.exists else 'MISSING'} {state.operstate or ''}".rstrip())
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
