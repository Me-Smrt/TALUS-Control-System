from __future__ import annotations

import re

_THINK_BLOCK = re.compile(r"<think\b[^>]*>.*?</think\s*>", re.IGNORECASE | re.DOTALL)
_OPEN_THINK = re.compile(r"<think\b[^>]*>", re.IGNORECASE)
_CLOSE_THINK = re.compile(r"</think\s*>", re.IGNORECASE)


def clean_visible_answer(text: str) -> str:
    """Remove hidden-reasoning markup from text intended for display/TTS.

    Some multimodal Qwen/llama.cpp combinations have occasionally returned an
    orphan ``</think>`` marker with a draft before it and the real final answer
    after it.  For user-visible output, content after the final orphan closing
    marker is authoritative. Complete ``<think>...</think>`` blocks are removed.

    This is intentionally conservative: ordinary prose is otherwise left alone.
    """
    value = str(text or "")
    if not value:
        return ""

    # Remove well-formed hidden-reasoning blocks first.
    value = _THINK_BLOCK.sub("", value)

    # If a closing marker remains without its opening marker, prefer the text
    # after the *last* close. This matches the observed VLM failure mode where a
    # draft leaked before </think> and the polished final answer followed it.
    closes = list(_CLOSE_THINK.finditer(value))
    if closes:
        tail = value[closes[-1].end():].strip()
        if tail:
            value = tail
        else:
            value = _CLOSE_THINK.sub("", value)

    # An unmatched opening marker means everything after it is hidden scratch.
    opener = _OPEN_THINK.search(value)
    if opener:
        value = value[:opener.start()]

    value = _OPEN_THINK.sub("", value)
    value = _CLOSE_THINK.sub("", value)
    return value.strip()
