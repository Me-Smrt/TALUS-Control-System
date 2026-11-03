from __future__ import annotations

import platform
from pathlib import Path
from typing import Any


class AudioDeviceProbe:
    """Best-effort USB audio inventory.

    Audio transport is intentionally not implemented in this control pass.  The
    Pi will own the microphone/speaker, but the exact STT/TTS audio contract is
    left for the auxiliary-computer R&D pass.  This probe gives the dashboard a
    truthful 'present / not yet present / backend unavailable' status meanwhile.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        cfg = config or {}
        self.input_match = str(cfg.get("input_name_contains", "")).casefold()
        self.output_match = str(cfg.get("output_name_contains", "")).casefold()
        self.input_label = str(cfg.get("input_label", "USB microphone"))
        self.output_label = str(cfg.get("output_label", "USB speaker"))

    @staticmethod
    def _linux_cards() -> list[str]:
        path = Path("/proc/asound/cards")
        try:
            return [line.strip() for line in path.read_text(errors="ignore").splitlines() if line.strip()]
        except Exception:
            return []

    def probe(self) -> dict[str, Any]:
        cards = self._linux_cards() if platform.system() == "Linux" else []
        joined = "\n".join(cards).casefold()
        input_present = bool(self.input_match and self.input_match in joined) if cards else None
        output_present = bool(self.output_match and self.output_match in joined) if cards else None
        status_for = lambda present: "online" if present is True else ("offline" if present is False else "unverified")
        return {
            "input": {
                "label": self.input_label,
                "status": status_for(input_present),
                "present": input_present,
                "match": self.input_match or None,
            },
            "output": {
                "label": self.output_label,
                "status": status_for(output_present),
                "present": output_present,
                "match": self.output_match or None,
            },
            "backend": "alsa_cards_probe" if cards else "not_available_in_current_environment",
            "audio_transport": "reserved_for_auxiliary_rnd",
        }
