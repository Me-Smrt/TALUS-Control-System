from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np


def load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def clamp01(value: float) -> float:
    return clamp(float(value), 0.0, 1.0)


def safe_normalize(vector: np.ndarray, fallback: np.ndarray | None = None) -> np.ndarray:
    vector = np.asarray(vector, dtype=float)
    norm = float(np.linalg.norm(vector))
    if norm > 1e-9:
        return vector / norm
    if fallback is None:
        return np.zeros_like(vector)
    fallback = np.asarray(fallback, dtype=float)
    fn = float(np.linalg.norm(fallback))
    return fallback / fn if fn > 1e-9 else np.zeros_like(vector)


def angle_between(a: np.ndarray, b: np.ndarray) -> float:
    a = safe_normalize(a)
    b = safe_normalize(b)
    dot = clamp(float(np.dot(a, b)), -1.0, 1.0)
    return math.acos(dot)


def as_builtin(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if isinstance(value, dict):
        return {str(k): as_builtin(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [as_builtin(v) for v in value]
    return value
