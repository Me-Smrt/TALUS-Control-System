from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .util import as_builtin


class JsonlRecorder:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open("a", encoding="utf-8", buffering=1)

    def write(self, payload: dict[str, Any]) -> None:
        self.file.write(json.dumps(as_builtin(payload), separators=(",", ":"), allow_nan=False) + "\n")

    def close(self) -> None:
        self.file.close()
