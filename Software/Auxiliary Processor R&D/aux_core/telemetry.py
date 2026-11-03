from __future__ import annotations

import json
import math
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def _finite(value: Any) -> float | None:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if math.isfinite(n) else None


def _mean(values: Iterable[Any]) -> float | None:
    nums = [n for n in (_finite(v) for v in values) if n is not None]
    return (sum(nums) / len(nums)) if nums else None


class TelemetryStore:
    """Small append-only local evaluation/telemetry store.

    JSONL keeps the R&D data inspectable with normal tools and avoids coupling
    early evaluation work to a database schema.  Only a bounded recent window is
    held in memory for the dashboard.
    """

    def __init__(self, cfg: dict[str, Any] | None, root: Path):
        self.cfg = dict(cfg or {})
        p = Path(str(self.cfg.get("path", "runtime/telemetry/turns.jsonl")))
        self.path = p if p.is_absolute() else (Path(root) / p).resolve()
        self.enabled = bool(self.cfg.get("enabled", True))
        self.max_recent = max(20, int(self.cfg.get("max_recent", 500)))
        self.dashboard_window = max(5, int(self.cfg.get("dashboard_window", 100)))
        self._lock = threading.RLock()
        self._recent: deque[dict[str, Any]] = deque(maxlen=self.max_recent)
        self._load_recent()

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    def _load_recent(self) -> None:
        if not self.enabled or not self.path.is_file():
            return
        try:
            lines = self.path.read_text(encoding="utf-8", errors="replace").splitlines()[-self.max_recent :]
            for line in lines:
                try:
                    item = json.loads(line)
                    if isinstance(item, dict):
                        self._recent.append(item)
                except Exception:
                    continue
        except Exception:
            pass

    def record(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        event = {"timestamp": self._timestamp(), "event_type": str(event_type), **dict(payload)}
        if not self.enabled:
            return event
        encoded = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(encoded + "\n")
            self._recent.append(event)
        return event

    def record_turn(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.record("conversation_turn", payload)

    def record_stt_eval(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.record("stt_eval", payload)

    def recent(self, event_type: str | None = None, *, limit: int | None = None) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._recent)
        if event_type:
            items = [x for x in items if x.get("event_type") == event_type]
        if limit is not None:
            items = items[-max(0, int(limit)) :]
        return items

    def snapshot(self) -> dict[str, Any]:
        turns = self.recent("conversation_turn", limit=self.dashboard_window)
        stt = self.recent("stt_eval", limit=self.dashboard_window)
        llm = [x.get("llm", {}) for x in turns if isinstance(x.get("llm"), dict)]
        rag_attempts = [x for x in turns if x.get("rag_attempted")]
        rag_hits = [x for x in rag_attempts if int(x.get("rag_hits") or 0) > 0]
        deep = [x for x in turns if x.get("reasoning_mode") == "deep"]
        vision = [x for x in turns if x.get("visual_used")]
        token_rates = [x.get("tokens_per_second") for x in llm]
        exact_token_turns = sum(1 for x in llm if x.get("token_count_source") == "api")

        latest = turns[-1] if turns else None
        last_stt = stt[-1] if stt else None
        return {
            "schema": "automaton.aux_telemetry.v1",
            "enabled": self.enabled,
            "path": str(self.path),
            "window_turns": len(turns),
            "totals": {
                "recent_events": len(self.recent()),
                "conversation_turns": len(turns),
                "stt_evaluations": len(stt),
            },
            "averages": {
                "turn_ms": _mean(x.get("turn_ms") for x in turns),
                "llm_total_ms": _mean(x.get("total_ms") for x in llm),
                "llm_ttft_ms": _mean(x.get("ttft_ms") for x in llm),
                "tokens_per_second": _mean(token_rates),
                "completion_tokens": _mean(x.get("completion_tokens") for x in llm),
                "stt_rtf": _mean(x.get("rtf") for x in stt),
                "stt_wer": _mean(x.get("wer") for x in stt),
            },
            "rates": {
                "deep_reasoning": (len(deep) / len(turns)) if turns else None,
                "vision_used": (len(vision) / len(turns)) if turns else None,
                "rag_attempted": (len(rag_attempts) / len(turns)) if turns else None,
                "rag_hit_when_attempted": (len(rag_hits) / len(rag_attempts)) if rag_attempts else None,
                "exact_llm_token_count": (exact_token_turns / len(llm)) if llm else None,
            },
            "latest_turn": latest,
            "latest_stt_eval": last_stt,
        }
