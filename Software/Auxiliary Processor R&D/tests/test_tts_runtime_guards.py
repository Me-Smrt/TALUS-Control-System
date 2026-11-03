import io
import tempfile
import wave
from pathlib import Path

import pytest

from aux_core.tts import NoSpeakableText, PiperCliBackend, _has_speakable_text


def test_short_streaming_label_fragment_is_not_speakable():
    assert not _has_speakable_text('d:')
    assert not _has_speakable_text('Vietnamese:')
    assert _has_speakable_text('Xin chào')


def test_piper_wav_validator_accepts_real_pcm():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / 'ok.wav'
        with wave.open(str(path), 'wb') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(22050)
            wav_file.writeframes(b'\x00\x00' * 32)
        assert PiperCliBackend._validate_wav(path) == (1, 32, 22050)


def test_piper_wav_validator_rejects_empty_file():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / 'empty.wav'
        path.write_bytes(b'')
        with pytest.raises(RuntimeError, match='valid WAV'):
            PiperCliBackend._validate_wav(path)


def test_piper_child_forces_utf8_for_cyrillic(monkeypatch, tmp_path):
    backend = PiperCliBackend({'binary': 'piper'}, tmp_path)
    model = tmp_path / 'ru_RU-denis-medium.onnx'
    model.write_bytes(b'model')
    voice = {
        'id': 'piper_ru_ru_denis_medium',
        'language': 'ru-RU',
        'model_path': str(model),
    }

    monkeypatch.setattr(backend, 'available', lambda _voice: True)
    monkeypatch.setattr('aux_core.tts.os.name', 'nt')
    observed = {}

    class Result:
        returncode = 0
        stdout = b''
        stderr = b''

    def fake_run(args, **kwargs):
        observed['env'] = kwargs.get('env', {})
        observed['input'] = kwargs.get('input')
        out_path = Path(args[args.index('--output_file') + 1])
        with wave.open(str(out_path), 'wb') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(22050)
            wav_file.writeframes(b'\x00\x00' * 16)
        return Result()

    monkeypatch.setattr('aux_core.tts.subprocess.run', fake_run)
    payload = backend.synthesize('Здравствуйте.', voice)
    assert payload.startswith(b'RIFF')
    assert observed['env']['PYTHONUTF8'] == '1'
    assert observed['env']['PYTHONIOENCODING'] == 'utf-8'
    assert observed['input'] == 'Здравствуйте.\n'.encode('utf-8')


def test_piper_linux_path_does_not_require_windows_utf8_env(monkeypatch, tmp_path):
    backend = PiperCliBackend({'binary': 'piper'}, tmp_path)
    model = tmp_path / 'de_DE-thorsten-medium.onnx'
    model.write_bytes(b'model')
    voice = {
        'id': 'piper_de_de_thorsten_medium',
        'language': 'de-DE',
        'model_path': str(model),
    }

    monkeypatch.setattr(backend, 'available', lambda _voice: True)
    monkeypatch.setattr('aux_core.tts.os.name', 'posix')
    observed = {}

    class Result:
        returncode = 0
        stdout = b''
        stderr = b''

    def fake_run(args, **kwargs):
        observed['env'] = kwargs.get('env', {})
        out_path = Path(args[args.index('--output_file') + 1])
        with wave.open(str(out_path), 'wb') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(22050)
            wav_file.writeframes(b'\x00\x00' * 16)
        return Result()

    monkeypatch.setattr('aux_core.tts.subprocess.run', fake_run)
    payload = backend.synthesize('Grüße.', voice)
    assert payload.startswith(b'RIFF')
    assert observed['env'].get('PYTHONUTF8') is None
    assert observed['env'].get('PYTHONIOENCODING') is None
