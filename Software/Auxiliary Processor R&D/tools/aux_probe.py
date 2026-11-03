from __future__ import annotations

import argparse
import json
import urllib.request


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://127.0.0.1:8770")
    p.add_argument("--token", default="")
    args = p.parse_args()
    headers = {"Accept": "application/json"}
    if args.token:
        headers["Authorization"] = "Bearer " + args.token
    for endpoint in ("/v1/health", "/v1/status", "/v1/voices", "/v1/contract"):
        req = urllib.request.Request(args.base.rstrip("/") + endpoint, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=3) as r:
                payload = json.loads(r.read().decode("utf-8"))
            print(f"\n{endpoint} [{r.status}]")
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        except Exception as exc:
            print(f"\n{endpoint} ERROR: {exc}")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
