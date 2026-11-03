from pathlib import Path
import re

OVERLAY = Path(__file__).resolve().parents[1] / "overlays" / "automaton-ccb-8can-overlay.dts"


def test_overlay_contains_all_eight_mcp25625_channels():
    text = OVERLAY.read_text()
    assert text.count('compatible = "microchip,mcp25625";') == 8
    assert [int(x) for x in re.findall(r'can@(\d+) \{', text)] == list(range(8))
    assert 'clock-frequency = <20000000>;' in text


def test_overlay_uses_exact_ccb_cs_and_level_low_interrupts():
    text = OVERLAY.read_text()
    cs = [int(x) for x in re.findall(r'<&gpio (\d+) 1>', text)]
    assert cs[:8] == [8, 7, 4, 17, 27, 22, 23, 24]
    irqs = [(int(pin), int(flags)) for pin, flags in re.findall(r'interrupts = <(\d+) (\d+)>;', text)]
    assert irqs == [(25,8), (5,8), (6,8), (12,8), (13,8), (19,8), (16,8), (26,8)]
