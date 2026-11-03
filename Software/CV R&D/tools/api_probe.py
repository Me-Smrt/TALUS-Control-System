from __future__ import annotations

import argparse
import json
import os
import urllib.request


def main() -> int:
    p = argparse.ArgumentParser(description="Probe the local Automaton Pi read-only API")
    p.add_argument("--base", default="http://127.0.0.1:8766")
    p.add_argument("--token", default=os.getenv("AUTOMATON_API_TOKEN", ""))
    args = p.parse_args()
    req = urllib.request.Request(args.base.rstrip("/") + "/v1/state")
    if args.token:
        req.add_header("Authorization", f"Bearer {args.token}")
    with urllib.request.urlopen(req, timeout=2.0) as response:
        print(json.dumps(json.load(response), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
