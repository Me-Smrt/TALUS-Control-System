from __future__ import annotations

import argparse
import io
import json
import re
import sys
import tempfile
import time
import wave
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aux_core.config import load_json, resolve_path
from aux_core.stt import FasterWhisperStt
from aux_core.telemetry import TelemetryStore
from aux_core.tts import TtsManager
from aux_core.util import language_family
from aux_core.voices import VoiceRegistry


SAMPLES = {
    "en": "Hello, this is a speech recognition test for TALUS.",
    "es": "Hola, esta es una prueba de reconocimiento de voz para TALUS.",
    "fr": "Bonjour, ceci est un test de reconnaissance vocale pour TALUS.",
    "de": "Hallo, dies ist ein Spracherkennungstest für TALUS.",
    "it": "Ciao, questo è un test di riconoscimento vocale per TALUS.",
    "pt": "Olá, este é um teste de reconhecimento de fala para TALUS.",
    "ru": "Здравствуйте, это тест распознавания речи для TALUS.",
    "ja": "こんにちは、これはTALUSの音声認識テストです。",
    "zh": "你好，这是TALUS的语音识别测试。",
    "ko": "안녕하세요. 이것은 TALUS의 음성 인식 테스트입니다.",
    "nl": "Hallo, dit is een spraakherkenningstest voor TALUS.",
    "pl": "Cześć, to jest test rozpoznawania mowy dla TALUS.",
    "tr": "Merhaba, bu TALUS için bir konuşma tanıma testidir.",
    "uk": "Привіт, це тест розпізнавання мовлення для TALUS.",
    "vi": "Xin chào, đây là bài kiểm tra nhận dạng giọng nói cho TALUS.",
    "ar": "مرحبًا، هذا اختبار للتعرف على الكلام لنظام TALUS.",
    "hi": "नमस्ते, यह TALUS के लिए वाक् पहचान परीक्षण है।",
    "id": "Halo, ini adalah tes pengenalan suara untuk TALUS.",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Evaluate Faster-Whisper with repeatable synthetic or supplied audio.")
    p.add_argument("--config", type=Path, default=ROOT / "config/default.json")
    p.add_argument("--voices", type=Path, default=ROOT / "config/voices.json")
    p.add_argument("--voice-set", default="best_available", help="Voice set used to generate synthetic test audio.")
    p.add_argument("--languages", default=",".join(SAMPLES), help="Comma-separated synthetic language families.")
    p.add_argument("--audio", type=Path, help="Evaluate one existing WAV/audio file instead of generating synthetic audio.")
    p.add_argument("--expected", help="Expected transcript for --audio mode.")
    p.add_argument("--language", help="Expected language family for --audio mode. STT is still allowed to auto-detect it.")
    p.add_argument("--keep-audio", action="store_true", help="Keep generated WAVs in runtime/telemetry/stt_samples.")
    p.add_argument("--report", type=Path, default=ROOT / "runtime/telemetry/stt_eval_latest.json")
    return p.parse_args()


def _norm_words(text: str) -> list[str]:
    return re.findall(r"\w+", str(text).casefold(), flags=re.UNICODE)


def _norm_chars(text: str) -> list[str]:
    return [c for c in str(text).casefold() if c.isalnum()]


def _edit_distance(a: list[str], b: list[str]) -> int:
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(cur[-1] + 1, prev[j] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def _error_rate(expected: Iterable[str], actual: Iterable[str]) -> float | None:
    ref = list(expected)
    hyp = list(actual)
    if not ref:
        return 0.0 if not hyp else None
    return _edit_distance(ref, hyp) / len(ref)


def _wav_duration(wav_bytes: bytes) -> float:
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def _file_duration(path: Path) -> float | None:
    try:
        with wave.open(str(path), "rb") as w:
            return w.getnframes() / float(w.getframerate())
    except Exception:
        return None


def evaluate_one(stt: FasterWhisperStt, audio, expected: str | None, expected_language: str | None) -> dict:
    duration_s = _file_duration(Path(audio)) if isinstance(audio, (str, Path)) else None
    started = time.perf_counter()
    out = stt.transcribe(audio, language=None)
    elapsed_s = time.perf_counter() - started
    detected = language_family(out.get("language"))
    wanted = language_family(expected_language)
    row = {
        "expected_language": wanted if wanted != "und" else None,
        "detected_language": detected if detected != "und" else out.get("language"),
        "language_probability": out.get("language_probability"),
        "language_match": (wanted == detected) if wanted != "und" else None,
        "expected_text": expected,
        "transcript": out.get("text", ""),
        "audio_duration_s": round(duration_s, 4) if duration_s is not None else None,
        "transcription_s": round(elapsed_s, 4),
        "rtf": round(elapsed_s / duration_s, 4) if duration_s and duration_s > 0 else None,
    }
    if expected is not None:
        row["wer"] = _error_rate(_norm_words(expected), _norm_words(row["transcript"]))
        row["cer"] = _error_rate(_norm_chars(expected), _norm_chars(row["transcript"]))
    return row


def main() -> int:
    a = parse_args()
    cfg = load_json(a.config)
    stt = FasterWhisperStt(cfg["stt"], ROOT)
    telemetry = TelemetryStore(cfg.get("telemetry", {}), ROOT)
    results: list[dict] = []

    if a.audio:
        if not a.audio.is_file():
            raise SystemExit(f"Audio file not found: {a.audio}")
        row = evaluate_one(stt, a.audio, a.expected, a.language)
        row["source"] = "file"
        row["audio_path"] = str(a.audio.resolve())
        results.append(row)
    else:
        runtime = resolve_path(ROOT, cfg["tts"].get("runtime_path", "runtime/tts_state.json"))
        voices = VoiceRegistry(a.voices, runtime, cfg["tts"]["default_voice_id"])
        tts = TtsManager(cfg["tts"], voices, ROOT)
        languages = [language_family(x.strip()) for x in a.languages.split(",") if x.strip()]
        keep_dir = ROOT / "runtime/telemetry/stt_samples"
        if a.keep_audio:
            keep_dir.mkdir(parents=True, exist_ok=True)

        print(f"[STT EVAL] Synthetic TTS→STT baseline using voice set {a.voice_set!r}")
        for lang in languages:
            expected = SAMPLES.get(lang)
            if not expected:
                print(f"SKIP {lang:<3} no built-in sample")
                continue
            try:
                wav, voice = tts.synthesize(
                    expected, voice_set_id=a.voice_set, language=lang, auto_language=False
                )
            except Exception as exc:
                row = {"source": "synthetic", "expected_language": lang, "expected_text": expected, "error": str(exc)}
                results.append(row)
                print(f"FAIL {lang:<3} TTS: {exc}")
                continue
            duration_s = _wav_duration(wav)
            if a.keep_audio:
                path = keep_dir / f"{lang}_{voice['id']}.wav"
                path.write_bytes(wav)
                audio_path = path
                cleanup = False
            else:
                temp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                path = Path(temp.name)
                temp.close()
                path.write_bytes(wav)
                audio_path = path
                cleanup = True
            try:
                row = evaluate_one(stt, audio_path, expected, lang)
            finally:
                if cleanup:
                    path.unlink(missing_ok=True)
            row.update({"source": "synthetic", "tts_voice_id": voice.get("id"), "tts_voice_set": a.voice_set, "audio_duration_s": round(duration_s, 4)})
            results.append(row)
            wer = row.get("wer")
            wer_txt = f"WER {wer:.1%}" if isinstance(wer, float) else "WER —"
            prob = row.get("language_probability")
            prob_txt = f"{float(prob):.0%}" if prob is not None else "—"
            match = "OK" if row.get("language_match") is True else "LANG?"
            print(f"{match:<5} {lang:<3} → {str(row.get('detected_language')):<3} ({prob_txt})  {wer_txt:<10} RTF {row.get('rtf')}  {voice.get('id')}")

    valid = [r for r in results if not r.get("error")]
    summary = {
        "schema": "automaton.stt_eval.v1",
        "generated_at": time.time(),
        "mode": "file" if a.audio else "synthetic",
        "count": len(results),
        "successful": len(valid),
        "language_accuracy": (sum(1 for r in valid if r.get("language_match") is True) / sum(1 for r in valid if r.get("language_match") is not None)) if any(r.get("language_match") is not None for r in valid) else None,
        "average_wer": (sum(float(r["wer"]) for r in valid if r.get("wer") is not None) / sum(1 for r in valid if r.get("wer") is not None)) if any(r.get("wer") is not None for r in valid) else None,
        "average_cer": (sum(float(r["cer"]) for r in valid if r.get("cer") is not None) / sum(1 for r in valid if r.get("cer") is not None)) if any(r.get("cer") is not None for r in valid) else None,
        "average_rtf": (sum(float(r["rtf"]) for r in valid if r.get("rtf") is not None) / sum(1 for r in valid if r.get("rtf") is not None)) if any(r.get("rtf") is not None for r in valid) else None,
        "results": results,
    }
    a.report.parent.mkdir(parents=True, exist_ok=True)
    a.report.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for row in valid:
        telemetry.record_stt_eval({k: v for k, v in row.items() if k not in {"expected_text", "transcript"}})
    print(f"[STT EVAL] Report: {a.report}")
    print(
        "[STT EVAL] "
        f"language accuracy={summary['language_accuracy'] if summary['language_accuracy'] is not None else '—'}  "
        f"avg WER={summary['average_wer'] if summary['average_wer'] is not None else '—'}  "
        f"avg RTF={summary['average_rtf'] if summary['average_rtf'] is not None else '—'}"
    )
    return 0 if len(valid) == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
