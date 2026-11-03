from __future__ import annotations

import argparse
import json
from pathlib import Path

from aux_core.people import PersonStore

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    p = argparse.ArgumentParser(description="Inspect the Automaton local people/memory database")
    p.add_argument("action", choices=["list", "show", "delete"])
    p.add_argument("person_id", nargs="?")
    args = p.parse_args()

    cfg = json.loads((ROOT / "config/default.json").read_text(encoding="utf-8"))
    store = PersonStore(cfg.get("people", {}), ROOT)

    if args.action == "list":
        people = store.list_people()
        if not people:
            print("No enrolled people.")
            return 0
        for person in people:
            print(f"{person['person_id']}  {person['name']}  last_seen={person['last_seen']:.0f}  seen={person['seen_count']}")
        return 0

    if not args.person_id:
        p.error("person_id is required for show/delete")

    if args.action == "show":
        person = store.get(args.person_id)
        if not person:
            print("Person not found")
            return 1
        print(json.dumps({**person, "memories": store.memories(args.person_id)}, indent=2, ensure_ascii=False))
        return 0

    removed = store.delete(args.person_id)
    print("Deleted" if removed else "Person not found")
    return 0 if removed else 1


if __name__ == "__main__":
    raise SystemExit(main())
