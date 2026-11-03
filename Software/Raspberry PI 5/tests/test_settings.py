from pathlib import Path
import pytest

from automaton.settings import load_settings


def test_default_settings_when_missing(tmp_path: Path):
    s = load_settings(tmp_path / "missing.toml")
    assert s.can.bitrate == 500_000
    assert s.can.interfaces == tuple(f"can{i}" for i in range(8))
    assert s.supervisor.heartbeat_gpio == 18


def test_bitrate_is_loaded_from_config(tmp_path: Path):
    p = tmp_path / "automaton.toml"
    p.write_text('''
[can]
bitrate = 250000
restart_ms = 250
interfaces = ["can0", "can3"]
''')
    s = load_settings(p)
    assert s.can.bitrate == 250_000
    assert s.can.restart_ms == 250
    assert s.can.interfaces == ("can0", "can3")


def test_invalid_bitrate_rejected(tmp_path: Path):
    p = tmp_path / "automaton.toml"
    p.write_text("[can]\nbitrate = 5000000\n")
    with pytest.raises(ValueError):
        load_settings(p)
