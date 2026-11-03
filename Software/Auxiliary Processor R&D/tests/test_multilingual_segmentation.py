from aux_core.language import detect_text_language, split_text_language_spans


CANDIDATES = {
    "en", "es", "fr", "de", "it", "pt", "ja", "zh", "hi", "ko", "ar",
    "ru", "uk", "nl", "pl", "tr", "id", "vi",
}


def test_script_languages_route_without_langdetect_guesswork():
    assert detect_text_language("안녕하세요! 로봇에 대해 이야기해 주세요.", candidates=CANDIDATES)[0] == "ko"
    assert detect_text_language("مرحبًا! أخبرني عن الروبوتات.", candidates=CANDIDATES)[0] == "ar"
    assert detect_text_language("Привет! Расскажи о роботах.", candidates=CANDIDATES)[0] == "ru"
    assert detect_text_language("Привіт! Розкажи про роботів.", candidates=CANDIDATES)[0] == "uk"


def test_mixed_english_spanish_french_is_split_at_sentence_boundaries():
    text = 'English: Hello! Spanish: ¡Hola! ¿Cómo estás? French: Bonjour ! Comment vas-tu ?'
    spans = split_text_language_spans(text, candidates=CANDIDATES)
    langs = [lang for _text, lang in spans]
    assert "en" in langs
    assert "es" in langs
    assert "fr" in langs
    assert len(spans) >= 3


def test_latin_to_japanese_switch_is_split_immediately():
    text = "Japanese: こんにちは！今日は元気ですか？"
    spans = split_text_language_spans(text, candidates=CANDIDATES)
    assert any(lang == "ja" for _text, lang in spans)


def test_single_language_text_stays_one_span_for_prosody():
    text = "Hello there. This is a normal English paragraph with two sentences."
    spans = split_text_language_spans(text, candidates=CANDIDATES)
    assert len(spans) == 1
    assert spans[0][0] == text


def test_language_labels_are_metadata_not_spoken_payload():
    text = 'Arabic: مرحبا\nGerman: Guten Tag\nVietnamese: Xin chào'
    spans = split_text_language_spans(text, candidates=CANDIDATES)
    combined = ' | '.join(span for span, _lang in spans)
    assert 'Arabic:' not in combined
    assert 'German:' not in combined
    assert 'Vietnamese:' not in combined
    assert 'مرحبا' in combined
    assert 'Guten Tag' in combined
    assert 'Xin chào' in combined


def test_mandarin_chinese_compound_label_stays_together():
    spans = split_text_language_spans('Korean: 안녕하세요\nMandarin Chinese: 你好', candidates=CANDIDATES)
    assert spans == [('안녕하세요', 'ko'), ('你好', 'zh')]


def test_short_english_streaming_greeting_uses_lexical_evidence():
    # This exact style of streamed fragment was being classified as Turkish by
    # langdetect on the Windows R&D machine. Deterministic vocabulary evidence
    # should win before the broad statistical detector.
    assert detect_text_language("Hi Tyler! Welcome back.", candidates=CANDIDATES)[0] == "en"
    assert detect_text_language("I'm ready to help whenever you are.", candidates=CANDIDATES)[0] == "en"
