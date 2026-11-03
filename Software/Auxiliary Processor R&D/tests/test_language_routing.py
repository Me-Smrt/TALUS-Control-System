from aux_core.language import (
    detect_text_language,
    requested_response_language,
    split_text_language_spans,
)

CANDIDATES = {
    "en", "es", "fr", "de", "it", "pt", "ja", "zh", "hi", "ko", "ar",
    "ru", "uk", "nl", "pl", "tr", "id", "vi",
}


def test_english_story_does_not_jump_to_vietnamese():
    text = (
        "Once, a robot named Talus roamed Tennessee Tech. "
        "He saw a robot garden, then a robot lab. "
        "He felt a robot heart beat, then a robot mind thought."
    )
    spans = split_text_language_spans(text, hint="en", candidates=CANDIDATES)
    assert spans
    assert {lang for _span, lang in spans} == {"en"}


def test_explicit_translation_language_is_detected():
    assert requested_response_language("Convert that story into Spanish.") == "es"
    assert requested_response_language("Can you convert these list items into German and read them back?") == "de"
    assert requested_response_language("We can go back to English now.") == "en"
    assert requested_response_language("And German.") == "de"
    assert requested_response_language("And finally manderin.") == "zh"


def test_named_target_language_can_seed_streaming_hysteresis():
    text = "Una vez, un robot llamado Talus caminaba por Tennessee Tech."
    spans = split_text_language_spans(text, hint="es", candidates=CANDIDATES)
    assert spans
    assert {lang for _span, lang in spans} == {"es"}


def test_long_clear_span_still_switches_when_language_is_genuine():
    text = "Hola, muchas gracias. Me gustaría hablar contigo en español ahora."
    lang, confidence = detect_text_language(text, hint="en", candidates=CANDIDATES)
    assert lang == "es"
    assert confidence >= 0.95
