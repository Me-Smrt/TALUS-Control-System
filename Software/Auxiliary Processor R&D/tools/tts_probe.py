from __future__ import annotations

import argparse
import io
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aux_core.config import load_json, resolve_path
from aux_core.tts import TtsManager
from aux_core.util import language_family
from aux_core.voices import VoiceRegistry


SAMPLES = {
    'en': 'Hello.',
    'ar': 'مرحبا',
    'nl': 'Hallo',
    'fr': 'Bonjour',
    'de': 'Guten Tag',
    'hi': 'नमस्ते',
    'id': 'Halo',
    'it': 'Ciao',
    'ja': 'こんにちは',
    'ko': '안녕하세요',
    'zh': '你好',
    'pl': 'Cześć',
    'pt': 'Olá',
    'ru': 'Здравствуйте',
    'es': 'Hola',
    'tr': 'Merhaba',
    'uk': 'Привіт',
    'vi': 'Xin chào',
}


def wav_summary(payload: bytes) -> str:
    with wave.open(io.BytesIO(payload), 'rb') as wav_file:
        return f"{wav_file.getnframes()} frames @ {wav_file.getframerate()} Hz"


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Actually synthesize short native-language samples to verify TALUS TTS runtime routes.'
    )
    parser.add_argument('--voice-set', help='Probe a specific voice set (female, male, best_available).')
    parser.add_argument('--all-voices', action='store_true', help='Probe every installed configured voice instead of one route per language.')
    args = parser.parse_args()

    cfg = load_json(ROOT / 'config/default.json')
    runtime = resolve_path(ROOT, cfg['tts'].get('runtime_path', 'runtime/tts_state.json'))
    registry = VoiceRegistry(ROOT / 'config/voices.json', runtime, cfg['tts']['default_voice_id'])
    tts = TtsManager(cfg['tts'], registry, ROOT)
    failures = 0

    if args.all_voices:
        rows = []
        for voice in tts.list_voices():
            if not voice.get('available'):
                continue
            langs = [language_family(x) for x in voice.get('languages', [])]
            lang = next((x for x in langs if x in SAMPLES), 'en')
            rows.append((lang, voice['id']))
        print(f'[TTS PROBE] Testing {len(rows)} installed voices...')
        for lang, voice_id in rows:
            sample = SAMPLES[lang]
            try:
                wav, used = tts.synthesize(sample, voice_id=voice_id, language=lang, auto_language=False)
                print(f"OK   {lang:>2}  {used['id']:<40} {wav_summary(wav)}")
            except Exception as exc:
                failures += 1
                print(f"FAIL {lang:>2}  {voice_id:<40} {exc}")
    else:
        voice_set = args.voice_set or registry.active_set_id
        print(f"[TTS PROBE] Voice set: {voice_set or 'individual/default'}")
        for lang, sample in SAMPLES.items():
            try:
                wav, used = tts.synthesize(sample, voice_set_id=voice_set, language=lang, auto_language=False)
                print(f"OK   {lang:>2}  {used['id']:<40} {wav_summary(wav)}")
            except Exception as exc:
                failures += 1
                print(f"FAIL {lang:>2}  {'route':<40} {exc}")

    print(f"[TTS PROBE] {'PASS' if failures == 0 else 'FAIL'}: {failures} failure(s)")
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
