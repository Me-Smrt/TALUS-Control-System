from __future__ import annotations
from typing import Protocol

class DigitalOutput(Protocol):
    def write(self, level: bool) -> None: ...
    def close(self) -> None: ...

class NullOutput:
    def __init__(self) -> None:
        self.level = False
    def write(self, level: bool) -> None:
        self.level = bool(level)
    def close(self) -> None:
        self.level = False

class GpioZeroOutput:
    """Small adapter around GPIO Zero, the Raspberry Pi documented Python GPIO API.

    Import is delayed so unit tests and non-Pi development do not require gpiozero.
    """
    def __init__(self, bcm_pin: int):
        try:
            from gpiozero import DigitalOutputDevice  # type: ignore
        except ImportError as exc:
            raise RuntimeError("gpiozero is required for the CCB heartbeat GPIO on Raspberry Pi") from exc
        self._device = DigitalOutputDevice(bcm_pin, active_high=True, initial_value=False)

    def write(self, level: bool) -> None:
        self._device.on() if level else self._device.off()

    def close(self) -> None:
        self._device.off()
        self._device.close()
