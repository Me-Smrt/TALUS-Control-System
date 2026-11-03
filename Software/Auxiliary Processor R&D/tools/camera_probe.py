from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aux_core.config import load_json  # noqa: E402
from aux_core.pi_client import PiClient  # noqa: E402


def main() -> int:
    cfg = load_json(ROOT / "config/default.json")
    pi = PiClient(cfg["pi"])
    print(f"Pi API: {pi.base}")
    try:
        payload = pi.cameras()
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    except Exception as exc:
        print(f"ERROR reading /v1/cameras: {exc}")
        return 2

    selected = pi.choose_camera()
    print(f"Selected camera: {selected}")
    try:
        jpeg, headers = pi.frame(selected, view="raw")
        print(f"Frame OK: {len(jpeg)} bytes")
        print(f"Camera header: {headers.get('X-Automaton-Camera', selected)}")
        print(f"Frame age ms: {headers.get('X-Automaton-Frame-Age-Ms', '?')}")
        return 0
    except Exception as exc:
        print(f"ERROR requesting frame from {selected}: {exc}")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
