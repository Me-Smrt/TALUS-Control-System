from unittest.mock import patch

import importlib.util
from pathlib import Path


SPEC = importlib.util.spec_from_file_location(
    "wake_alias_trainer_v053", Path(__file__).resolve().parents[1] / "tools" / "wake_alias_trainer.py"
)
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def _payload(alias, share, *, exact=0.5, samples=20):
    return {
        "summary": {
            "usable_samples": samples,
            "exact_rate": exact,
            "mode": {"text": alias, "share": share},
            "mean_similarity": 0.9,
            "suggested_aliases": [{"alias": alias, "share": share, "count": max(2, int(samples * share))}],
        }
    }


def test_profile_slug_is_filesystem_safe():
    assert mod._profile_slug("USB mic / robot installed") == "USB_mic_robot_installed"


def test_primary_profile_is_weighted_more_heavily_in_comparison():
    data = {
        "laptop_mic": _payload("talos", 0.5),
        "robot_mic": _payload("talis", 0.5),
    }
    with patch.object(mod, "_load_profile", side_effect=lambda name: data[name]):
        out = mod._compare_profiles(["laptop_mic", "robot_mic"], primary="robot_mic")
    scores = {row["alias"]: row["weighted_score"] for row in out["recommended_alias_union"]}
    assert scores["talis"] == 1.0
    assert scores["talos"] == 0.5
    assert out["primary_profile"] == "robot_mic"
