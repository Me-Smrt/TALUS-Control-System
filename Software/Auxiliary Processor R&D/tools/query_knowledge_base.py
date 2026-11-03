from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# When this file is run as `python tools/query_knowledge_base.py`, Python puts
# tools/ rather than the project root on sys.path. Add the root explicitly so
# the same documented command works on Windows, Linux, and the eventual Orin.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aux_core.knowledge import LocalKnowledgeBase
from aux_core.config import load_json


def main() -> int:
    p = argparse.ArgumentParser(description="Inspect local Automaton knowledge retrieval without running the LLM")
    p.add_argument("query", nargs="+")
    p.add_argument("--config", type=Path, default=ROOT / "config/default.json")
    p.add_argument("--db", type=Path, default=None, help="Optional knowledge SQLite database override")
    a = p.parse_args()
    cfg = load_json(a.config)
    knowledge_cfg = dict(cfg.get("knowledge", {}))
    if a.db is not None:
        knowledge_cfg["database_path"] = str(a.db.resolve())
    kb = LocalKnowledgeBase(knowledge_cfg, ROOT)
    q = " ".join(a.query)
    hits = kb.retrieve(q)
    print(json.dumps({"status": kb.status(), "query": q, "hits": [h.public_dict() for h in hits]}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
