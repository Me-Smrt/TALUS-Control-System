from aux_core.language import detect_text_language, split_text_language_spans


CANDIDATES = {
    "en", "es", "fr", "de", "it", "pt", "ja", "zh", "hi", "ko", "ar",
    "ru", "uk", "nl", "pl", "tr", "id", "vi",
}


def test_short_ambiguous_latin_fragments_inherit_english_hint():
    for text in ("Chem HW4", "ECE HW", "Math", "AEE Finalization", "Submit ECE HW"):
        lang, confidence = detect_text_language(text, hint="en", candidates=CANDIDATES)
        assert lang == "en"
        assert confidence == 0.0 or confidence >= 0.80


def test_checklist_stays_english_when_turn_is_english():
    text = "Chem HW4. ECE HW. Math. AEE Finalization. Submit ECE HW."
    spans = split_text_language_spans(text, hint="en", candidates=CANDIDATES)
    assert spans
    assert {lang for _span, lang in spans} == {"en"}


def test_long_confident_span_can_switch_away_from_english_hint():
    text = "Hola, muchas gracias. Me gustaría hablar contigo en español ahora."
    lang, confidence = detect_text_language(text, hint="en", candidates=CANDIDATES)
    assert lang == "es"
    assert confidence >= 0.80


def test_strong_script_switch_ignores_latin_hysteresis():
    assert detect_text_language("こんにちは", hint="en", candidates=CANDIDATES)[0] == "ja"
    assert detect_text_language("Привет", hint="en", candidates=CANDIDATES)[0] == "ru"
    assert detect_text_language("مرحبا", hint="en", candidates=CANDIDATES)[0] == "ar"
