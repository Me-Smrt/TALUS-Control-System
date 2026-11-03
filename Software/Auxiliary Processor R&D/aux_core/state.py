from __future__ import annotations
import copy, threading, time
from typing import Any

class AuxiliaryState:
    def __init__(self, version: str = "0.1.0") -> None:
        self._lock = threading.RLock(); self._started = time.monotonic(); self._seq = 0
        self._state: dict[str, Any] = {
            "schema":"automaton.aux_state.v1", "service_version":version, "sequence":0,
            "status":"starting", "uptime_s":0.0,
            "components":{
                "llm":"unprobed","stt":"unprobed","tts":"unprobed","vision":"unprobed",
                "pi_link":"unprobed","audio":"disabled","knowledge":"unprobed","identity":"unprobed"
            },
            "conversation":{
                "state":"idle","language":None,"last_user_text":None,"last_reply_text":None,
                "last_turn_ms":None,"reasoning_mode":"fast","reasoning_reason":"startup"
            },
            "voice":{"active_id":None,"backend":None,"available":False},
            "vision":{"last_camera":None,"last_objects":[],"last_description":None},
            "engagement":{"state":"idle","score":0.0,"reason":"startup"},
            "knowledge":{"available":False,"documents":0,"chunks":0,"last_query":None,"last_sources":[],"hits":0},
            "people":{"face_present":False,"current_person_id":None,"current_name":None,"match_score":None,"identity_backend_available":False,"people_count":0,"memory_count":0,"last_event":"startup"},
            "scheduler":{"queued":0,"active":None},
        }
    def update(self, section: str | None = None, **values: Any) -> None:
        with self._lock:
            target = self._state if section is None else self._state.setdefault(section,{})
            target.update(copy.deepcopy(values)); self._seq += 1; self._state["sequence"] = self._seq
    def component(self, name: str, status: str) -> None:
        with self._lock:
            self._state["components"][name] = str(status); self._seq += 1; self._state["sequence"] = self._seq
    def snapshot(self) -> dict[str, Any]:
        with self._lock: out=copy.deepcopy(self._state)
        out["uptime_s"] = max(0.0, time.monotonic()-self._started)
        return out
