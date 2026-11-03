import importlib.util
from pathlib import Path


SPEC = importlib.util.spec_from_file_location(
    "wake_alias_trainer", Path(__file__).resolve().parents[1] / "tools" / "wake_alias_trainer.py"
)
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def test_alias_analysis_suggests_repeated_misreading():
    rows = []
    for candidate in ["talos"] * 12 + ["talus"] * 6 + ["talis"] * 2:
        rows.append({
            "candidate": candidate,
            "similarity": mod._similarity(candidate, "TALUS"),
            "edit_distance": mod._levenshtein(candidate, "talus"),
            "language_probability": 0.99,
            "transcription_s": 1.0,
        })
    out = mod._analyze(rows, "TALUS", {"talus", "talis"}, 0.10, 2)
    assert out["mode"]["text"] == "talos"
    assert any(x["alias"] == "talos" for x in out["suggested_aliases"])
    assert out["mean_edit_distance"] > 0


def test_best_token_finds_name_inside_longer_transcript():
    assert mod._best_token("hey Talos can you hear me", "TALUS") == "talos"
