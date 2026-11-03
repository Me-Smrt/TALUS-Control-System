from aux_core.tts import prepare_text_for_speech


def test_markdown_is_not_spoken_literally():
    src = "**Hello!** Here is *important* text and [the campus page](https://www.tntech.edu/)."
    out = prepare_text_for_speech(src)
    assert "*" not in out
    assert "https://" not in out
    assert "Hello!" in out
    assert "important" in out
    assert "the campus page" in out


def test_fenced_code_is_omitted_by_default():
    src = "Try this:\n```python\nprint('hello')\n```\nThen continue."
    out = prepare_text_for_speech(src)
    assert "print" not in out
    assert "Code example omitted from speech" in out
    assert "Then continue" in out


def test_lists_become_speakable_prose():
    src = "- First item\n- Second item\n1. Third item"
    out = prepare_text_for_speech(src)
    assert "First item" in out and "Second item" in out and "Third item" in out
    assert "-" not in out
