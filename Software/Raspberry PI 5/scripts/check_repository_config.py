#!/usr/bin/env python3
"""Development-time consistency check for Pi/RCB CAN configuration.

This is intentionally a repository helper rather than a runtime handshake: if the two CAN
controllers are compiled/configured at different bitrates, they cannot communicate well
enough to negotiate the error over CAN.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from automaton.can_timing import require_supported_bitrate
from automaton.settings import load_settings

BITRATE_FLAG_RE = re.compile(r"-DAUTOMATON_CAN_BITRATE\s*=\s*([0-9_]+)(?:UL|LU|U|L)?\b")


def read_rcb_bitrate(platformio_path: Path) -> int:
    text = platformio_path.read_text(encoding="utf-8")
    match = BITRATE_FLAG_RE.search(text)
    if not match:
        raise ValueError(f"AUTOMATON_CAN_BITRATE build flag not found in {platformio_path}")
    return int(match.group(1).replace("_", ""))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    default_software_root = ROOT.parent
    ap.add_argument("--pi-config", type=Path, default=ROOT / "config" / "automaton.toml")
    ap.add_argument(
        "--rcb-platformio",
        type=Path,
        default=default_software_root / "Remote Control Module" / "platformio.ini",
    )
    args = ap.parse_args(argv)

    settings = load_settings(args.pi_config)
    pi_bitrate = settings.can.bitrate
    rcb_bitrate = read_rcb_bitrate(args.rcb_platformio)

    pi_timing = require_supported_bitrate(pi_bitrate)
    rcb_timing = require_supported_bitrate(rcb_bitrate)

    print(
        f"Pi bitrate:  {pi_bitrate} bit/s "
        f"(actual={pi_timing.actual_bitrate}, sample={pi_timing.sample_point_permille / 10:.1f}%)"
    )
    print(
        f"RCB bitrate: {rcb_bitrate} bit/s "
        f"(actual={rcb_timing.actual_bitrate}, sample={rcb_timing.sample_point_permille / 10:.1f}%)"
    )

    if pi_bitrate != rcb_bitrate:
        print("ERROR: Pi and RCB CAN bitrates do not match.", file=sys.stderr)
        return 2

    print("OK: Pi and RCB CAN bitrate configuration matches.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
