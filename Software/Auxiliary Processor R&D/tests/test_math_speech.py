from aux_core.speech_stream import SpeechChunker
from aux_core.tts import prepare_text_for_speech


def test_wye_delta_equation_is_spoken_without_latex_punctuation():
    src = r"""
**Wye to Delta**
$$
R_{ab} = \frac{R_a R_b + R_b R_c + R_c R_a}{R_c}
$$
"""
    out = prepare_text_for_speech(src)
    low = out.lower()
    assert "$" not in out
    assert "\\frac" not in out
    assert "{" not in out and "}" not in out
    assert "r sub a b equals" in low
    assert "r sub a times r sub b" in low
    assert "divided by the quantity r sub c" in low


def test_inline_math_is_verbalized():
    out = prepare_text_for_speech(r"Use $V = I R$ and $P = V^2/R$.")
    low = out.lower()
    assert "v equals i times r" in low
    assert "v squared" in low
    assert "divided by r" in low


def test_stream_chunker_does_not_split_inside_display_math():
    c = SpeechChunker(first_min_chars=10, first_max_chars=35, min_chars=10, max_chars=35)
    first = c.feed("Here is the equation: $$R_{ab} = ")
    assert first == []
    second = c.feed(r"\frac{R_a R_b}{R_c}$$. Then continue. ")
    assert second
    assert "$$" in second[0]
    assert second[0].count("$$") == 2
