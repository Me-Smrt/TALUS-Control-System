from __future__ import annotations

import re
from typing import Iterable

# Small deterministic fallback used when langdetect is unavailable or uncertain.
# It is intentionally only a fallback; the packaged detector remains the primary
# path for Latin-script languages.
_COMMON_WORDS: dict[str, set[str]] = {
    "en": {"the", "and", "you", "your", "is", "are", "what", "how", "hello", "hi", "thanks", "with", "this", "that", "for", "can", "would", "like", "welcome", "back", "ready", "help", "whenever", "please", "sure", "good", "there", "once", "named", "saw", "garden", "then", "lab", "felt", "heart", "beat", "mind", "thought", "loved", "worlds", "holding", "piece", "paper", "list", "story", "robot"},
    "es": {"hola", "gracias", "que", "qué", "como", "cómo", "estas", "estás", "todo", "bien", "aqui", "aquí", "nuevo", "claro", "me", "alegra", "quieras", "seguir", "practicando", "algo", "especifico", "específico", "espanol", "español", "puedo", "ayudarte", "vocabulario", "frases"},
    "fr": {"bonjour", "merci", "comment", "vous", "tu", "avec", "pour", "est", "suis", "bien", "quoi", "nouveau", "français", "francais"},
    "de": {"hallo", "danke", "wie", "geht", "dir", "ihnen", "und", "mit", "für", "fur", "ist", "was", "deutsch", "etwas", "über", "ueber", "robotik"},
    "it": {"ciao", "grazie", "come", "stai", "bene", "con", "per", "che", "italiano", "posso", "aiutarti"},
    "pt": {"olá", "ola", "obrigado", "obrigada", "como", "você", "voce", "bem", "com", "para", "que", "português", "portugues"},
    "nl": {"hallo", "dank", "hoe", "gaat", "met", "jou", "robotica", "vertel", "iets", "over", "vandaag"},
    "pl": {"cześć", "czesc", "dziękuję", "dziekuje", "jak", "się", "sie", "robotyce", "robotyka", "opowiedz", "proszę", "prosze"},
    "tr": {"merhaba", "teşekkürler", "tesekkurler", "nasılsın", "nasilsin", "robotik", "hakkında", "hakkinda", "bana", "anlat"},
    "id": {"halo", "terima", "kasih", "apa", "kabar", "robotika", "tentang", "ceritakan", "saya", "anda"},
    "vi": {"xin", "chào", "chao", "cảm", "ơn", "cam", "on", "bạn", "ban", "hãy", "hay", "kể", "ke", "về", "ve"},
}

_LANGUAGE_LABELS = (
    # Put compound labels before their shorter prefixes so a line such as
    # ``Mandarin Chinese: 你好`` is treated as one metadata label rather than
    # splitting into ``Mandarin`` + ``Chinese: ...`` while tokens stream in.
    "mandarin chinese",
    "english", "spanish", "french", "german", "italian", "portuguese", "hindi",
    "japanese", "chinese", "mandarin", "korean", "arabic", "russian", "dutch",
    "polish", "turkish", "ukrainian", "indonesian", "vietnamese",
)
_LABEL_TOKEN = re.compile(r"(?i)\b(?P<label>" + "|".join(_LANGUAGE_LABELS) + r")\s*:")
_SENTENCE_OR_LINE = re.compile(r".+?(?:[.!?。！？؟]+(?:[\"'”’»）)\]]*)?(?:\s+|$)|\n+|$)", re.DOTALL)
_LABEL_TO_LANGUAGE = {
    "mandarin chinese": "zh",
    "english": "en", "spanish": "es", "french": "fr", "german": "de",
    "italian": "it", "portuguese": "pt", "hindi": "hi", "japanese": "ja",
    "chinese": "zh", "mandarin": "zh", "korean": "ko", "arabic": "ar",
    "russian": "ru", "dutch": "nl", "polish": "pl", "turkish": "tr",
    "ukrainian": "uk", "indonesian": "id", "vietnamese": "vi",
}
_LABEL_AT_START = re.compile(r"^\s*[*_`\"'“”‘’]*(?P<label>" + "|".join(_LANGUAGE_LABELS) + r")[*_`\"'“”‘’]*\s*:", re.I)


def _split_on_language_labels(text: str) -> list[str]:
    """Split at recognized language headings without overlapping compound labels."""
    value = str(text or "")
    matches = list(_LABEL_TOKEN.finditer(value))
    if not matches:
        return [value] if value else []
    parts: list[str] = []
    if matches[0].start() > 0:
        parts.append(value[:matches[0].start()])
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(value)
        parts.append(value[match.start():end])
    return [part for part in parts if part]


def _family(code: str | None) -> str | None:
    if not code:
        return None
    value = str(code).replace("_", "-").split("-", 1)[0].lower().strip()
    return value or None


def _script_language(text: str) -> tuple[str, float] | None:
    # Kana is unambiguously Japanese for our supported set. If kana is present,
    # any Han characters in the same span are also part of the Japanese text.
    if re.search(r"[\u3040-\u30ff]", text):
        return "ja", 1.0
    if re.search(r"[\uac00-\ud7af\u1100-\u11ff]", text):
        return "ko", 1.0
    if re.search(r"[\u0900-\u097f]", text):
        return "hi", 1.0
    if re.search(r"[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff]", text):
        return "ar", 1.0
    # Ukrainian has several letters that are strong discriminators from Russian.
    if re.search(r"[іїєґІЇЄҐ]", text):
        return "uk", 0.99
    if re.search(r"[\u0400-\u04ff]", text):
        return "ru", 0.96
    # Han without kana is routed to Mandarin.
    if re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", text):
        return "zh", 0.99
    return None


def _lexical_fallback(text: str, candidates: set[str]) -> tuple[str, float] | None:
    words = re.findall(r"[^\W\d_]+", text.casefold(), flags=re.UNICODE)
    if not words:
        return None
    scores: list[tuple[int, str]] = []
    for lang, vocabulary in _COMMON_WORDS.items():
        if lang not in candidates:
            continue
        score = sum(1 for word in words if word in vocabulary)
        if lang == "es" and ("¡" in text or "¿" in text):
            score += 2
        scores.append((score, lang))
    if not scores:
        return None
    scores.sort(reverse=True)
    best_score, best_lang = scores[0]
    second_score = scores[1][0] if len(scores) > 1 else 0
    if best_score <= 0 or best_score == second_score:
        return None
    if best_score >= 3:
        confidence = 0.99
    elif best_score >= 2:
        confidence = 0.97
    else:
        confidence = 0.82
    return best_lang, confidence




# Human-facing language names/aliases used to detect an explicit requested
# response language (for example, "translate that into Spanish" or the terse
# follow-up "And German.").  This is deliberately deterministic: when the user
# names the output language we should not make the streaming TTS router infer it
# again from the first few generated words.
_REQUEST_LANGUAGE_ALIASES: dict[str, str] = {
    "english": "en", "ingles": "en", "inglés": "en",
    "spanish": "es", "espanol": "es", "español": "es",
    "french": "fr", "francais": "fr", "français": "fr",
    "german": "de", "deutsch": "de",
    "italian": "it", "italiano": "it",
    "portuguese": "pt", "portugues": "pt", "português": "pt",
    "japanese": "ja", "nihongo": "ja",
    "chinese": "zh", "mandarin": "zh", "manderin": "zh", "mandarin chinese": "zh",
    "korean": "ko",
    "hindi": "hi",
    "arabic": "ar",
    "russian": "ru",
    "ukrainian": "uk",
    "dutch": "nl",
    "polish": "pl",
    "turkish": "tr",
    "indonesian": "id",
    "vietnamese": "vi",
}
_REQUEST_CUES = re.compile(
    r"(?i)\b(?:translate|convert|say|speak|read|answer|respond|reply|language|into|in|back\s+to|switch\s+to|finally)\b"
)

def requested_response_language(text: str) -> str | None:
    """Return an explicitly requested output language, if one is named.

    This is intentionally conservative and is used as a routing prior, not as a
    general semantic-language classifier.  A bare language name is accepted for
    terse continuation turns such as ``And German.``; otherwise a translation/
    response cue must also be present.
    """
    value = str(text or "").strip()
    if not value:
        return None
    folded = value.casefold()
    matches: list[tuple[int, int, str]] = []
    # Longest aliases first so "mandarin chinese" wins over "mandarin".
    for alias in sorted(_REQUEST_LANGUAGE_ALIASES, key=len, reverse=True):
        m = re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", folded)
        if m:
            matches.append((m.start(), m.end(), _REQUEST_LANGUAGE_ALIASES[alias]))
    if not matches:
        return None
    matches.sort(key=lambda row: row[0])
    unique = []
    for _start, _end, code in matches:
        if code not in unique:
            unique.append(code)
    if len(unique) != 1:
        return None
    # "And German." / "And finally Mandarin." are common translation followups.
    terse = re.fullmatch(
        r"(?is)\s*(?:and\s+)?(?:finally\s+)?(?:in\s+)?[\wÀ-ž]+(?:\s+[\wÀ-ž]+)?[.!?]*\s*",
        value,
    )
    if terse or _REQUEST_CUES.search(value):
        return unique[0]
    return None


def _has_distinctive_latin_signal(text: str, lang: str) -> bool:
    """Whether a Latin-script span contains language-specific orthography.

    This is only a switch guard. It prevents a high-confidence statistical guess
    on generic ASCII text from changing voices while still allowing obvious
    Spanish/French/German/etc. text to switch without an explicit user request.
    """
    patterns = {
        "es": r"[¿¡ñáéíóúü]",
        "fr": r"[àâçéèêëîïôûùüÿœæ]",
        "de": r"[äöüß]",
        "it": r"[àèéìíîòóùú]",
        "pt": r"[ãõáâàçéêíóôú]",
        "nl": r"[ëïéè]",
        "pl": r"[ąćęłńóśźż]",
        "tr": r"[çğıİöşü]",
        "vi": r"[ăâđêôơưáàảãạấầẩẫậắằẳẵặéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ]",
    }
    pattern = patterns.get(lang)
    return bool(pattern and re.search(pattern, text, re.IGNORECASE))


def detect_text_language(
    text: str,
    *,
    hint: str | None = None,
    candidates: Iterable[str] | None = None,
    min_confidence: float = 0.80,
    switch_min_confidence: float = 0.95,
    switch_min_words: int = 4,
    inherit_short_latin_from_hint: bool = True,
) -> tuple[str | None, float]:
    """Detect the dominant language of a TTS span without network access.

    ``hint`` is used only when detection is unavailable/uncertain. The detector
    is constrained to languages for which TALUS has configured voice routes so
    an unrelated classification cannot select a nonsense voice.
    """
    value = str(text or "").strip()
    hint_family = _family(hint)
    candidate_set = {_family(x) for x in (candidates or [])}
    candidate_set.discard(None)
    if not candidate_set:
        candidate_set = {
            "en", "es", "fr", "de", "it", "pt", "ja", "zh", "hi", "ko",
            "ar", "ru", "uk", "nl", "pl", "tr", "id", "vi",
        }

    scripted = _script_language(value)
    deferred_scripted = None
    if scripted and scripted[0] in candidate_set:
        # Russian and Ukrainian share Cyrillic heavily. If both routes exist and
        # no Ukrainian-specific letter was present, let the lexical detector
        # distinguish them before using Russian as the conservative fallback.
        if scripted[0] == "ru" and "uk" in candidate_set:
            deferred_scripted = scripted
        else:
            return scripted

    # Prefer deterministic lexical evidence before the statistical detector.
    # Streaming TTS often sees short sentence fragments (for example
    # "Hi Tyler! Welcome back."). langdetect is intentionally broad and can
    # assign a high-confidence but implausible language to very short Latin
    # fragments. Known-language words are more reliable for this routing job.
    fallback = _lexical_fallback(value, candidate_set)
    if fallback and fallback[1] >= float(min_confidence):
        # Staying in the active Latin-script language is cheap; switching away
        # from it requires stronger lexical evidence. This is intentional
        # hysteresis for streamed speech. A generic word such as "robot" must
        # never be enough to turn an English sentence into Vietnamese.
        if hint_family and fallback[0] != hint_family:
            if fallback[1] >= float(switch_min_confidence):
                return fallback
        else:
            return fallback

    latin_words = re.findall(r"[^\W\d_]+", value.casefold(), flags=re.UNICODE)

    # Use langdetect for longer/less-obvious Latin-script spans. It is a tiny
    # offline package and ships its language profiles with the wheel; no model
    # is downloaded at runtime.
    if value:
        try:
            from langdetect import DetectorFactory, detect_langs
            from langdetect.lang_detect_exception import LangDetectException

            DetectorFactory.seed = 0
            try:
                guesses = detect_langs(value)
            except LangDetectException:
                guesses = []
            for guess in guesses:
                lang = _family(getattr(guess, "lang", None))
                confidence = float(getattr(guess, "prob", 0.0) or 0.0)
                if lang not in candidate_set or confidence < float(min_confidence):
                    continue
                if hint_family and lang != hint_family:
                    # Hysteresis: switching between Latin-script languages must
                    # clear a higher bar than staying in the current language.
                    # langdetect can report very high confidence on generic short
                    # ASCII phrases, so confidence alone is not sufficient.
                    if inherit_short_latin_from_hint and len(latin_words) < max(1, int(switch_min_words)):
                        continue
                    if confidence < float(switch_min_confidence):
                        continue
                    strong_lexical = bool(
                        fallback
                        and fallback[0] == lang
                        and fallback[1] >= float(switch_min_confidence)
                    )
                    distinctive = _has_distinctive_latin_signal(value, lang)
                    very_long = len(latin_words) >= 12 and confidence >= 0.995
                    if not (strong_lexical or distinctive or very_long):
                        continue
                return lang, confidence
        except Exception:
            pass
    if deferred_scripted is not None:
        return deferred_scripted
    return hint_family, 0.0


def _script_class(ch: str, *, japanese_context: bool = False) -> str | None:
    o = ord(ch)
    if 0x3040 <= o <= 0x30FF:
        return "ja"
    if 0x3400 <= o <= 0x4DBF or 0x4E00 <= o <= 0x9FFF:
        return "ja" if japanese_context else "zh"
    if 0xAC00 <= o <= 0xD7AF or 0x1100 <= o <= 0x11FF:
        return "ko"
    if 0x0900 <= o <= 0x097F:
        return "hi"
    if 0x0600 <= o <= 0x06FF or 0x0750 <= o <= 0x077F or 0x08A0 <= o <= 0x08FF:
        return "ar"
    if 0x0400 <= o <= 0x04FF:
        return "uk" if ch in "іїєґІЇЄҐ" else "ru"
    if ch.isalpha():
        return "latin"
    return None


def _split_script_runs(text: str) -> list[str]:
    """Split only at meaningful alphabet/script changes.

    Spaces and punctuation stay with the preceding run. Han characters are
    treated as Japanese when kana exists anywhere in the same source span.
    """
    value = str(text)
    if not value:
        return []
    japanese_context = bool(re.search(r"[\u3040-\u30ff]", value))
    runs: list[str] = []
    buf: list[str] = []
    current: str | None = None

    for ch in value:
        cls = _script_class(ch, japanese_context=japanese_context)
        if cls is None:
            buf.append(ch)
            continue
        if current is None:
            current = cls
            buf.append(ch)
            continue
        # Russian/Ukrainian share Cyrillic; don't split on one discriminator.
        same_cyrillic = {current, cls} <= {"ru", "uk"}
        if cls != current and not same_cyrillic:
            chunk = "".join(buf)
            if chunk:
                runs.append(chunk)
            buf = [ch]
            current = cls
        else:
            buf.append(ch)
            if cls == "uk":
                current = "uk"
    if buf:
        runs.append("".join(buf))
    return runs


def split_text_language_spans(
    text: str,
    *,
    hint: str | None = None,
    candidates: Iterable[str] | None = None,
    min_confidence: float = 0.80,
    switch_min_confidence: float = 0.95,
    switch_min_words: int = 4,
    inherit_short_latin_from_hint: bool = True,
) -> list[tuple[str, str | None]]:
    """Split a mixed-language TTS chunk conservatively.

    Ordinary single-language prose remains one span, preserving prosody. Mixed
    text is divided at line/sentence/language-label boundaries and at strong
    script transitions (Latin -> Japanese/Hindi/Arabic/etc.). Adjacent spans
    that resolve to the same language are merged back together.
    """
    value = str(text or "")
    if not value.strip():
        return []

    candidate_set = {_family(x) for x in (candidates or [])}
    candidate_set.discard(None)

    # First create conservative structural atoms. Language-name labels such as
    # "Spanish:" are useful in multilingual demonstrations even though both
    # sides may use the Latin script.
    structural: list[str] = []
    for labeled in _split_on_language_labels(value):
        if not labeled:
            continue
        found = [m.group(0) for m in _SENTENCE_OR_LINE.finditer(labeled) if m.group(0)]
        structural.extend(found or [labeled])

    atoms: list[str] = []
    for part in structural:
        runs = _split_script_runs(part)
        atoms.extend(runs or [part])

    resolved: list[tuple[str, str | None]] = []
    prior = _family(hint)
    labels_stripped = False
    for atom in atoms:
        if not atom.strip():
            continue

        label_match = _LABEL_AT_START.match(atom)
        forced_label = _LABEL_TO_LANGUAGE.get(label_match.group("label").casefold()) if label_match else None
        speech_atom = atom
        if forced_label in candidate_set:
            lang, confidence = forced_label, 1.0
            # Language headings are display metadata, not speech payload. Keeping
            # them in the payload makes (for example) an Arabic voice first try
            # to pronounce the English word "Arabic" and can produce zero-audio
            # Piper jobs at streaming boundaries. Strip only known labels; normal
            # colons and ordinary prose remain untouched.
            speech_atom = atom[label_match.end():].strip() if label_match else atom
            labels_stripped = True
            if not speech_atom:
                prior = lang
                continue
        else:
            lang, confidence = detect_text_language(
                speech_atom,
                hint=prior or hint,
                candidates=candidate_set,
                min_confidence=min_confidence,
                switch_min_confidence=switch_min_confidence,
                switch_min_words=switch_min_words,
                inherit_short_latin_from_hint=inherit_short_latin_from_hint,
            )

        # A zero-confidence result is merely inherited context. Keep it so tiny
        # connector fragments don't force a spurious language switch.
        lang = _family(lang) or prior or _family(hint)
        if confidence > 0:
            prior = lang
        speech_atom = speech_atom.strip()
        if not speech_atom:
            continue
        if resolved and resolved[-1][1] == lang:
            resolved[-1] = (resolved[-1][0].rstrip() + " " + speech_atom.lstrip(), lang)
        else:
            resolved.append((speech_atom, lang))

    distinct = {lang for _span, lang in resolved if lang}
    if len(distinct) <= 1 and not labels_stripped:
        only = next(iter(distinct), _family(hint))
        return [(value.strip(), only)]

    return [(span.strip(), lang) for span, lang in resolved if span.strip()]
