from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class _LowPass:
    value: float | None = None

    def filter(self, x: float, alpha: float) -> float:
        if self.value is None:
            self.value = float(x)
        else:
            self.value = alpha * float(x) + (1.0 - alpha) * self.value
        return self.value


class OneEuroFilter:
    """Scalar One-Euro filter for low-latency motion smoothing."""

    def __init__(
        self,
        min_cutoff: float = 1.0,
        beta: float = 0.0,
        derivative_cutoff: float = 1.0,
    ) -> None:
        self.min_cutoff = float(min_cutoff)
        self.beta = float(beta)
        self.derivative_cutoff = float(derivative_cutoff)
        self._x = _LowPass()
        self._dx = _LowPass()
        self._last_raw: float | None = None
        self._last_t: float | None = None

    @staticmethod
    def _alpha(cutoff: float, dt: float) -> float:
        cutoff = max(float(cutoff), 1e-6)
        dt = max(float(dt), 1e-6)
        tau = 1.0 / (2.0 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def reset(self) -> None:
        self._x = _LowPass()
        self._dx = _LowPass()
        self._last_raw = None
        self._last_t = None

    def filter(self, x: float, timestamp_s: float) -> float:
        x = float(x)
        timestamp_s = float(timestamp_s)
        if self._last_t is None or self._last_raw is None:
            self._last_t = timestamp_s
            self._last_raw = x
            return self._x.filter(x, 1.0)

        dt = max(timestamp_s - self._last_t, 1e-4)
        derivative = (x - self._last_raw) / dt
        d_hat = self._dx.filter(
            derivative,
            self._alpha(self.derivative_cutoff, dt),
        )
        cutoff = self.min_cutoff + self.beta * abs(d_hat)
        x_hat = self._x.filter(x, self._alpha(cutoff, dt))

        self._last_t = timestamp_s
        self._last_raw = x
        return x_hat


class FilterBank:
    def __init__(self, min_cutoff: float, beta: float, derivative_cutoff: float) -> None:
        self.params = (min_cutoff, beta, derivative_cutoff)
        self.filters: dict[str, OneEuroFilter] = {}

    def reset(self) -> None:
        self.filters.clear()

    def value(self, key: str, value: float, timestamp_s: float) -> float:
        if key not in self.filters:
            self.filters[key] = OneEuroFilter(*self.params)
        return self.filters[key].filter(value, timestamp_s)
