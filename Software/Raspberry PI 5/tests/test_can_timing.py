import pytest
from automaton.can_timing import calculate_mcp25625_timing, require_supported_bitrate


def test_common_rates_exact_with_20mhz_clock():
    for bitrate in (125_000, 250_000, 500_000, 1_000_000):
        t = require_supported_bitrate(bitrate)
        assert t.actual_bitrate == bitrate
        assert t.error_ppm == 0


def test_800k_rejected_for_20mhz_clock():
    assert calculate_mcp25625_timing(800_000) is None
    with pytest.raises(ValueError, match="cannot be generated"):
        require_supported_bitrate(800_000)
