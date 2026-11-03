from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config/default.json").read_text(encoding="utf-8"))
VOICES = json.loads((ROOT / "config/voices.json").read_text(encoding="utf-8"))


def local(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else ROOT / p


def mark(ok: bool) -> str:
    return "OK" if ok else "MISSING"


def main() -> int:
    rows: list[tuple[str, bool, str]] = []
    print(f"Python {sys.version.split()[0]} ({sys.executable})")
    managed = CONFIG["llm"].get("managed_server", {})
    qwen = local(managed.get("model_path", "models/qwen/Qwen3.5-4B-Q4_K_M.gguf"))
    mmproj = local(managed.get("mmproj_path", "models/qwen/mmproj-Qwen3.5-4B-BF16.gguf"))
    rows.append(("Qwen GGUF", qwen.is_file(), str(qwen)))
    rows.append(("Qwen mmproj", mmproj.is_file(), str(mmproj)))
    local_server = ROOT / "runtime" / ("llama-server.exe" if __import__('os').name == 'nt' else "llama-server")
    rows.append(("llama-server", local_server.is_file() or shutil.which("llama-server") is not None, str(local_server)))

    stt = local(CONFIG["stt"]["model_path"])
    rows.append(("Faster-Whisper", stt.is_dir(), str(stt)))

    yolo = local(CONFIG["vision"]["detector"]["model_path"])
    rows.append(("YOLO detector", yolo.is_file(), str(yolo)))

    identity = CONFIG.get("identity", {})
    face_det = local(identity.get("detector_model_path", "models/face/face_detection_yunet_2023mar.onnx"))
    face_rec = local(identity.get("recognition_model_path", "models/face/face_recognition_sface_2021dec.onnx"))
    rows.append(("Face detector (YuNet)", face_det.is_file(), str(face_det)))
    rows.append(("Face recognizer (SFace)", face_rec.is_file(), str(face_rec)))

    kdir = local(CONFIG["tts"]["backends"]["kokoro"]["model_dir"])
    rows.append(("Kokoro Python pkg", importlib.util.find_spec("kokoro") is not None, "pip install -r requirements.txt"))
    rows.append(("Kokoro config", (kdir / "config.json").is_file(), str(kdir / "config.json")))
    rows.append(("Kokoro weights", (kdir / "kokoro-v1_0.pth").is_file(), str(kdir / "kokoro-v1_0.pth")))

    if any("ja" in voice.get("languages", []) for voice in VOICES.get("voices", []) if voice.get("enabled", True)):
        rows.append(("Japanese G2P (pyopenjtalk)", importlib.util.find_spec("pyopenjtalk") is not None, "pip install -r requirements.txt"))
        unidic_ok = False
        unidic_detail = "python -m unidic download"
        try:
            import unidic  # type: ignore
            dicdir = Path(unidic.DICDIR)
            unidic_ok = (dicdir / "mecabrc").is_file()
            unidic_detail = str(dicdir) if unidic_ok else f"{dicdir} (run: python -m unidic download)"
        except Exception:
            pass
        rows.append(("Japanese UniDic dictionary", unidic_ok, unidic_detail))

    for voice in VOICES.get("voices", []):
        if not voice.get("enabled", True):
            continue
        backend = voice.get("backend")
        if backend == "kokoro":
            path = kdir / voice.get("voice_file", f"voices/{voice.get('voice')}.pt")
            rows.append((f"Voice {voice['id']}", path.is_file(), str(path)))
        elif backend == "piper":
            path = local(voice.get("model_path", ""))
            config_path = local(voice.get("config_path", str(path) + ".json"))
            binary = CONFIG["tts"]["backends"]["piper"].get("binary", "piper")
            ok = bool(shutil.which(binary)) and path.is_file() and config_path.is_file()
            rows.append((f"Voice {voice['id']}", ok, f"{path} (+ .json; piper={binary})"))

    # Voice-set coverage is informational: a set may be usable for every language
    # while lacking an exact matching gender/style for some languages. TALUS then
    # keeps language correctness and falls back to another installed voice.
    enabled_voices = {v["id"]: v for v in VOICES.get("voices", []) if v.get("enabled", True)}
    families = sorted({str(lang).split("-")[0].lower() for v in enabled_voices.values() for lang in v.get("languages", []) if lang})
    fallback_map = dict(VOICES.get("fallback_language_voice", {}))
    for voice_set in VOICES.get("voice_sets", []):
        if not voice_set.get("enabled", True):
            continue
        mapped = dict(voice_set.get("language_voices", {}))
        exact = 0
        usable = 0
        for fam in families:
            vid = mapped.get(fam)
            voice = enabled_voices.get(vid) if vid else None
            if voice:
                backend = voice.get("backend")
                if backend == "kokoro":
                    path = kdir / voice.get("voice_file", f"voices/{voice.get('voice')}.pt")
                    available = path.is_file()
                elif backend == "piper":
                    path = local(voice.get("model_path", ""))
                    cfg_path = local(voice.get("config_path", str(path) + ".json"))
                    binary = CONFIG["tts"]["backends"]["piper"].get("binary", "piper")
                    available = bool(shutil.which(binary)) and path.is_file() and cfg_path.is_file()
                else:
                    available = False
                if available:
                    exact += 1
                    usable += 1
                    continue
            fallback_id = fallback_map.get(fam)
            fallback = enabled_voices.get(fallback_id) if fallback_id else None
            if fallback:
                if fallback.get("backend") == "kokoro":
                    fpath = kdir / fallback.get("voice_file", f"voices/{fallback.get('voice')}.pt")
                    available = fpath.is_file()
                elif fallback.get("backend") == "piper":
                    fpath = local(fallback.get("model_path", ""))
                    fcfg = local(fallback.get("config_path", str(fpath) + ".json"))
                    binary = CONFIG["tts"]["backends"]["piper"].get("binary", "piper")
                    available = bool(shutil.which(binary)) and fpath.is_file() and fcfg.is_file()
                else:
                    available = False
                if available:
                    usable += 1
        rows.append((f"Voice set {voice_set.get('id')}", usable == len(families), f"{exact}/{len(families)} exact; {usable}/{len(families)} usable"))

    kb = local(CONFIG.get("knowledge", {}).get("database_path", "runtime/knowledge.sqlite3"))
    rows.append(("Knowledge DB", kb.is_file(), str(kb)))

    width = max(len(name) for name, _, _ in rows)
    for name, ok, path in rows:
        print(f"{name:<{width}}  {mark(ok):7}  {path}")
    print("\nMissing optional voices/knowledge DB do not prevent text conversation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
