import importlib.util
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "tools/stt_eval.py"
spec = importlib.util.spec_from_file_location("stt_eval_tool", MODULE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_edit_metrics_exact_match():
    assert mod._error_rate(mod._norm_words("Hello world"), mod._norm_words("hello world")) == 0
    assert mod._error_rate(mod._norm_chars("Hola!"), mod._norm_chars("hola")) == 0


def test_edit_metrics_detect_substitution():
    assert mod._error_rate(["hello", "world"], ["hello", "robot"]) == 0.5
