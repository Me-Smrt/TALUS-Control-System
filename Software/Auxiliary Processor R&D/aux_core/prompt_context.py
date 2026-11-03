from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any


_LANGUAGE_NAMES = {
    "ar": "Arabic",
    "de": "German",
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "hi": "Hindi",
    "id": "Indonesian",
    "it": "Italian",
    "ja": "Japanese",
    "ko": "Korean",
    "nl": "Dutch",
    "pl": "Polish",
    "pt": "Portuguese",
    "ru": "Russian",
    "tr": "Turkish",
    "uk": "Ukrainian",
    "vi": "Vietnamese",
    "zh": "Mandarin Chinese",
}


def _resolve(root: Path, raw: Any) -> Path | None:
    text = str(raw or "").strip()
    if not text:
        return None
    p = Path(text)
    return p if p.is_absolute() else (root / p).resolve()


def _installed(path: Path | None) -> bool:
    return bool(path and path.exists())


def _yes_no(value: bool) -> str:
    return "installed" if value else "not installed"


def _voice_languages(voice: dict[str, Any]) -> list[str]:
    raw = [str(x).strip() for x in voice.get("languages", []) if str(x).strip()]
    if raw:
        return raw
    locale = str(voice.get("language", "")).strip()
    return [locale.split("-", 1)[0].lower()] if locale else []


def build_runtime_system_context(
    root: Path,
    cfg: dict[str, Any],
    *,
    tts: Any | None = None,
    voices: Any | None = None,
) -> str:
    """Build a truthful startup inventory for the system prompt.

    This describes installed local assets, not live sensor/link state. Live state is
    intentionally left to the per-turn context supplied by the Pi/Aux state path.
    """
    root = Path(root)

    llm_cfg = dict(cfg.get("llm", {}))
    managed = dict(llm_cfg.get("managed_server", {}))
    stt_cfg = dict(cfg.get("stt", {}))
    vision_cfg = dict(cfg.get("vision", {}).get("detector", {}))
    knowledge_cfg = dict(cfg.get("knowledge", {}))
    identity_cfg = dict(cfg.get("identity", {}))

    qwen = _resolve(root, managed.get("model_path"))
    mmproj = _resolve(root, managed.get("mmproj_path"))
    whisper = _resolve(root, stt_cfg.get("model_path"))
    yolo = _resolve(root, vision_cfg.get("model_path"))
    knowledge_db = _resolve(root, knowledge_cfg.get("database_path"))

    face_detector = _resolve(root, identity_cfg.get("detector_model_path", "models/face/face_detection_yunet_2023mar.onnx"))
    face_recognizer = _resolve(root, identity_cfg.get("recognition_model_path", "models/face/face_recognition_sface_2021dec.onnx"))

    lines = [
        "RUNTIME CAPABILITY INVENTORY (generated automatically at startup from local configuration/assets):",
        "- This inventory reports installed local capability assets. It does NOT prove a camera/microphone is active, a network link is online, or a physical action succeeded.",
        f"- Local conversational model: {_yes_no(_installed(qwen))} ({qwen.name if qwen else 'not configured'}).",
        f"- Multimodal projector: {_yes_no(_installed(mmproj))} ({mmproj.name if mmproj else 'not configured'}).",
        f"- Local speech-recognition model: {_yes_no(_installed(whisper))}; Faster-Whisper Python support is {'installed' if importlib.util.find_spec('faster_whisper') else 'not installed'}.",
        f"- Local object detector: {_yes_no(_installed(yolo))}; Ultralytics Python support is {'installed' if importlib.util.find_spec('ultralytics') else 'not installed'}.",
        f"- Local face-identity models: {_yes_no(_installed(face_detector) and _installed(face_recognizer))}. Face identity is personalization only, never authentication/authorization.",
        f"- Tennessee Tech local knowledge database: {_yes_no(_installed(knowledge_db))}.",
    ]

    available: list[dict[str, Any]] = []
    if tts is not None:
        try:
            available = [v for v in tts.list_voices() if bool(v.get("available"))]
        except Exception:
            available = []

    if available:
        lines.append("- Installed speech-synthesis voices available to the local TTS runtime:")
        grouped: dict[str, list[str]] = {}
        for voice in available:
            langs = _voice_languages(voice) or [str(voice.get("language", "unknown"))]
            for code in langs:
                family = code.split("-", 1)[0].lower()
                if family == "*":
                    continue
                language_name = _LANGUAGE_NAMES.get(family, code)
                description = (
                    f"{voice.get('display_name', voice.get('id', 'unnamed voice'))} "
                    f"(id={voice.get('id', 'unknown')}, backend={voice.get('backend', 'unknown')})"
                )
                grouped.setdefault(language_name, []).append(description)
        for language_name in sorted(grouped):
            lines.append(f"  - {language_name}: " + "; ".join(grouped[language_name]))
        families = sorted({code.split("-", 1)[0].lower() for v in available for code in _voice_languages(v) if code and code != "*"})
        readable = [_LANGUAGE_NAMES.get(code, code) for code in families]
        lines.append("- Installed spoken-language coverage: " + ", ".join(readable) + ".")
        try:
            voice_sets = tts.list_voice_sets()
        except Exception:
            voice_sets = []
        if voice_sets:
            lines.append("- Configured multilingual voice sets (coverage is generated from installed assets):")
            for voice_set in voice_sets:
                lines.append(
                    f"  - {voice_set.get('display_name', voice_set.get('id', 'unnamed'))}: "
                    f"{voice_set.get('exact_language_count', 0)}/{voice_set.get('total_language_count', 0)} "
                    "languages have an installed exact set match; other languages may use a correct-language fallback."
                )
        lines.append("- The speech layer may automatically route a reply to an installed language-specific voice. Do not claim that you manually changed voices unless an action/result explicitly confirms it.")
    else:
        lines.append("- No local speech-synthesis voice is currently confirmed available. Do not claim that spoken output is available.")

    lines.extend(
        [
            "- You may still understand or generate text in languages beyond the installed speech voices, but do not claim you can pronounce/speak an unlisted language through local TTS.",
            "- Restart the Aux service after adding/removing model or voice files so this inventory is regenerated.",
        ]
    )
    return "\n".join(lines)
