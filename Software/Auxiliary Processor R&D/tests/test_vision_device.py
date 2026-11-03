import sys
import types
from pathlib import Path

from aux_core.vision import UltralyticsDetector


def test_auto_device_resolves_to_cpu_without_cuda(monkeypatch, tmp_path):
    fake_torch = types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda: False))
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    detector = UltralyticsDetector({"enabled": True, "model_path": "x.pt", "device": "auto"}, tmp_path)
    assert detector._device() == "cpu"


def test_auto_device_resolves_to_first_cuda_device(monkeypatch, tmp_path):
    fake_torch = types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda: True))
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    detector = UltralyticsDetector({"enabled": True, "model_path": "x.pt", "device": "auto"}, tmp_path)
    assert detector._device() == 0


def test_explicit_device_is_preserved(tmp_path):
    detector = UltralyticsDetector({"enabled": True, "model_path": "x.pt", "device": "cpu"}, tmp_path)
    assert detector._device() == "cpu"
