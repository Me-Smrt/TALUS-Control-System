from __future__ import annotations

import random
import re
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class ReasoningDecision:
    mode: str
    reason: str
    score: float = 0.0
    verification_required: bool = False


class ReasoningPolicy:
    """Choose between low-latency and deep-reasoning profiles.

    The automatic path is deterministic and intentionally cheap: no extra LLM
    call is required merely to decide whether to think. Explicit /fast and
    /think requests still override the automatic score.

    v0.3.8 adds an important distinction between a conceptual explanation and
    a *quantitative engineering problem*. Speech-to-text often turns equations
    into prose ("twenty-two kilo-ohms") rather than mathematical notation, so
    the router cannot rely on '$', '=' or digits alone. Quantitative engineering
    prompts are promoted to deep reasoning and marked for a hidden verification
    pass before anything is presented/spoken to the user.
    """

    _ANALYSIS_RE = re.compile(
        r"\b(?:analy[sz]e|compare|evaluate|debug|diagnose|design|architect|plan|derive|prove|optimi[sz]e|trade[- ]?offs?|root cause|reason through|work out)\b",
        re.IGNORECASE,
    )
    _STEP_RE = re.compile(
        r"\b(?:first|second|third|then|next|also|however|alternatively|on the other hand|step \d+)\b",
        re.IGNORECASE,
    )
    _TECHNICAL_RE = re.compile(
        r"(?:```|traceback|exception|stack trace|equation|formula|algorithm|architecture|schematic|dependency|race condition)",
        re.IGNORECASE,
    )
    _CALC_RE = re.compile(
        r"\b(?:solve|calculate|compute|determine|derive|work\s+through|show\s+your\s+work|find\s+the\s+equivalent|nodal\s+analysis|mesh\s+analysis)\b",
        re.IGNORECASE,
    )
    _MATH_NOTATION_RE = re.compile(r"(?:\$[^$]+\$|[=±√∑∫]|\\frac|\\sqrt|\b(?:sin|cos|tan|log|ln)\s*\()", re.IGNORECASE)

    # Words/units likely to survive STT even when symbols and digits do not.
    _ENGINEERING_RE = re.compile(
        r"\b(?:circuit|resistor|resistance|impedance|capacitor|capacitance|inductor|inductance|voltage|current|power|wye|delta|star|mesh|node|nodal|thevenin|norton|equivalent|transform(?:ation)?|convert|conversion|configuration)\b",
        re.IGNORECASE,
    )
    _UNIT_RE = re.compile(
        r"\b(?:ohms?|kilo[- ]?ohms?|mega[- ]?ohms?|milliohms?|volts?|millivolts?|kilovolts?|amps?|amperes?|milliamps?|microamps?|watts?|kilowatts?|farads?|microfarads?|nanofarads?|henrys?|millihenrys?|hertz|kilohertz|megahertz)\b|[ΩΩ]",
        re.IGNORECASE,
    )
    _CONVERSION_RE = re.compile(
        r"\b(?:convert|conversion|transform|transformation|reduce|reduced|equivalent|continue|next step|how do i continue|how do i proceed)\b",
        re.IGNORECASE,
    )
    _NUMBER_WORD_RE = re.compile(
        r"\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million|point|half|quarter)\b",
        re.IGNORECASE,
    )
    _NUMBER_DIGIT_RE = re.compile(r"(?<![A-Za-z])[-+]?\d+(?:[.,]\d+)?(?:e[-+]?\d+)?", re.IGNORECASE)

    def __init__(self, cfg: dict | None = None):
        self.cfg = dict(cfg or {})
        self.default_mode = str(self.cfg.get("default_mode", "auto")).lower()
        self.min_chars = int(self.cfg.get("auto_min_chars", 360))
        self.threshold = float(self.cfg.get("auto_score_threshold", 2.75))
        self.keywords = [str(x).casefold() for x in self.cfg.get("deep_keywords", [])]
        self.quantitative_verification = bool(self.cfg.get("quantitative_verification", True))

    @classmethod
    def _quantitative_engineering(cls, text: str) -> tuple[bool, int, int]:
        unit_hits = len(cls._UNIT_RE.findall(text))
        number_hits = len(cls._NUMBER_DIGIT_RE.findall(text)) + len(cls._NUMBER_WORD_RE.findall(text))
        engineering = bool(cls._ENGINEERING_RE.search(text))
        conversion = bool(cls._CONVERSION_RE.search(text))
        calculation = bool(cls._CALC_RE.search(text))
        # STT may represent one value as several words ("one hundred eighty"),
        # so this threshold is intentionally permissive once engineering units
        # or conversion language make the numerical intent clear.
        quantitative = engineering and number_hits >= 2 and (unit_hits >= 1 or conversion or calculation)
        return quantitative, number_hits, unit_hits

    def choose(self, text: str, requested: str | None = None) -> ReasoningDecision:
        mode = str(requested or self.default_mode or "auto").strip().lower()
        quantitative, number_hits, unit_hits = self._quantitative_engineering(text)
        verify = bool(quantitative and self.quantitative_verification)

        if mode in {"fast", "deep"}:
            # /fast is an explicit latency override. /think still gets the
            # quantitative verification pass when the problem warrants it.
            return ReasoningDecision(
                mode,
                f"forced_{mode}",
                99.0 if mode == "deep" else 0.0,
                verification_required=bool(verify and mode == "deep"),
            )
        if mode != "auto":
            raise ValueError("reasoning_mode must be 'auto', 'fast', or 'deep'")

        low = str(text).casefold()
        score = 0.0
        reasons: list[str] = []

        for keyword in self.keywords:
            if keyword and keyword in low:
                score += 3.0
                reasons.append(f"keyword:{keyword}")
                break

        analysis_hits = len(self._ANALYSIS_RE.findall(text))
        if analysis_hits:
            add = min(2.0, 0.9 + 0.45 * (analysis_hits - 1))
            score += add
            reasons.append(f"analysis_terms:{analysis_hits}")

        step_hits = len(self._STEP_RE.findall(text))
        if step_hits >= 2:
            score += min(1.5, 0.5 + 0.25 * step_hits)
            reasons.append(f"multi_step:{step_hits}")

        q_count = text.count("?")
        if q_count >= 2:
            score += min(1.25, 0.5 + 0.25 * (q_count - 1))
            reasons.append(f"multi_question:{q_count}")

        if self._TECHNICAL_RE.search(text):
            score += 1.0
            reasons.append("technical_complexity")

        if self._CALC_RE.search(text):
            score += 1.5
            reasons.append("solve_or_calculate")
        if self._MATH_NOTATION_RE.search(text):
            score += 0.8
            reasons.append("math_notation")

        if quantitative:
            # This is deliberately enough to cross the default threshold on its
            # own. A numerical engineering problem should be solved privately
            # before TALUS starts speaking, even if STT stripped the notation.
            score += 3.25
            reasons.append(f"engineering_quantitative:n{number_hits}:u{unit_hits}")

        if len(text) >= self.min_chars:
            score += 0.8
            reasons.append("long_prompt")
        if len(text) >= self.min_chars * 2:
            score += 0.6
            reasons.append("very_long_prompt")

        # Enumerated tasks are usually better handled with a little planning.
        numbered = len(re.findall(r"(?:^|\n)\s*(?:\d+[.)]|[-*])\s+", text))
        if numbered >= 3:
            score += 1.0
            reasons.append(f"enumerated:{numbered}")

        if score >= self.threshold:
            return ReasoningDecision(
                "deep",
                "+".join(reasons) or "complexity_score",
                round(score, 2),
                verification_required=verify,
            )
        return ReasoningDecision(
            "fast",
            "default_fast" if not reasons else "below_threshold:" + "+".join(reasons),
            round(score, 2),
            verification_required=False,
        )


class ThinkingCueSequence:
    """Generate non-repeating-ish human-facing progress cues for deep reasoning."""

    def __init__(self, cfg: dict | None = None):
        cfg = dict(cfg or {})
        self.initial_delay_s = float(cfg.get("initial_wait_s", 4.0))
        self.repeat_wait_s = float(cfg.get("repeat_wait_s", 9.0))
        self.max_cues = int(cfg.get("max_wait_cues", 4))
        self.lines = [str(x).strip() for x in cfg.get("waiting_lines", []) if str(x).strip()]
        self._rng = random.Random()

    def schedule(
        self,
        *,
        min_initial_s: float | None = None,
        min_repeat_s: float | None = None,
    ) -> Iterable[tuple[float, str]]:
        if not self.lines or self.max_cues <= 0:
            return []
        pool = list(self.lines)
        self._rng.shuffle(pool)
        out: list[tuple[float, str]] = []
        initial = self.initial_delay_s
        repeat = self.repeat_wait_s
        if min_initial_s is not None:
            initial = max(initial, float(min_initial_s))
        if min_repeat_s is not None:
            repeat = max(repeat, float(min_repeat_s))
        delay = initial
        for i in range(self.max_cues):
            if i and i % len(pool) == 0:
                self._rng.shuffle(pool)
            out.append((delay, pool[i % len(pool)]))
            delay += repeat
        return out
