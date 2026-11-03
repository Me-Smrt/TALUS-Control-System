from __future__ import annotations
from dataclasses import dataclass

MCP25625_OSC_HZ = 20_000_000
MAX_BITRATE_ERROR_PPM = 5_000  # 0.5%; matches the RCB firmware search.


@dataclass(frozen=True)
class BitTiming:
    brp: int
    prop_seg: int
    phase_seg1: int
    phase_seg2: int
    sjw: int
    actual_bitrate: int
    sample_point_permille: int
    error_ppm: int


def calculate_mcp25625_timing(target_bitrate: int, oscillator_hz: int = MCP25625_OSC_HZ) -> BitTiming | None:
    """Mirror the RCB MCP25625 nominal-bit-timing search.

    This is not used to program the Linux controller (the kernel does that); it prevents
    configuration of a nominal bitrate the 20 MHz RCB controller cannot reproduce within
    the project's current 0.5% error budget.
    """
    if target_bitrate <= 0 or oscillator_hz <= 0:
        return None
    best: BitTiming | None = None
    best_key: tuple[int, int, int] | None = None
    target_sample = 800
    for brp in range(64):
        for prop in range(1, 9):
            for ps1 in range(1, 9):
                for ps2 in range(2, 9):
                    ntq = 1 + prop + ps1 + ps2
                    if not 8 <= ntq <= 25:
                        continue
                    divisor = 2 * (brp + 1) * ntq
                    actual = oscillator_hz // divisor
                    if actual == 0:
                        continue
                    error_ppm = abs(actual - target_bitrate) * 1_000_000 // target_bitrate
                    sample = (1 + prop + ps1) * 1000 // ntq
                    key = (error_ppm, abs(sample - target_sample), -ntq)
                    if best_key is None or key < best_key:
                        best_key = key
                        best = BitTiming(brp, prop, ps1, ps2, 1, actual, sample, error_ppm)
    if best is None or best.error_ppm > MAX_BITRATE_ERROR_PPM:
        return None
    return best


def require_supported_bitrate(target_bitrate: int) -> BitTiming:
    if not 10_000 <= target_bitrate <= 1_000_000:
        raise ValueError(f"CAN bitrate out of supported Classic CAN range: {target_bitrate}")
    timing = calculate_mcp25625_timing(target_bitrate)
    if timing is None:
        raise ValueError(
            f"CAN bitrate {target_bitrate} cannot be generated from the project's "
            f"{MCP25625_OSC_HZ // 1_000_000} MHz MCP25625 oscillator within "
            f"{MAX_BITRATE_ERROR_PPM / 1_000_000:.1%} error"
        )
    return timing
