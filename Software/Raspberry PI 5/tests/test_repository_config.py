from pathlib import Path
import importlib.util

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_repository_config.py"
spec = importlib.util.spec_from_file_location("check_repository_config", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


def test_reads_rcb_bitrate(tmp_path):
    ini = tmp_path / "platformio.ini"
    ini.write_text("build_flags =\n    -DAUTOMATON_CAN_BITRATE=250000UL\n")
    assert module.read_rcb_bitrate(ini) == 250_000


def test_reads_underscored_rcb_bitrate(tmp_path):
    ini = tmp_path / "platformio.ini"
    ini.write_text("build_flags = -DAUTOMATON_CAN_BITRATE = 1_000_000UL\n")
    assert module.read_rcb_bitrate(ini) == 1_000_000
