from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIPER_REPO_ID = "rhasspy/piper-voices"
KOKORO_REPO_ID = "hexgrad/Kokoro-82M"

# Baseline common-language Piper voices introduced in the multilingual pass.
PIPER_COMMON = {
    "de": "de/de_DE/thorsten/medium/de_DE-thorsten-medium.onnx",
    "ko": "ko/ko_KR/kss/medium/ko_KR-kss-medium.onnx",
    "ar": "ar/ar_JO/kareem/medium/ar_JO-kareem-medium.onnx",
    "ru": "ru/ru_RU/denis/medium/ru_RU-denis-medium.onnx",
    "nl": "nl/nl_NL/pim/medium/nl_NL-pim-medium.onnx",
    "pl": "pl/pl_PL/gosia/medium/pl_PL-gosia-medium.onnx",
    "tr": "tr/tr_TR/dfki/medium/tr_TR-dfki-medium.onnx",
    "uk": "uk/uk_UA/ukrainian_tts/medium/uk_UA-ukrainian_tts-medium.onnx",
    "id": "id/id_ID/news_tts/medium/id_ID-news_tts-medium.onnx",
    "vi": "vi/vi_VN/vais1000/medium/vi_VN-vais1000-medium.onnx",
}

# Extra assets that improve Male/Female voice-set coverage. Some languages have
# only one upstream voice/gender; TALUS intentionally falls back to the correct
# language rather than choosing a wrong-language voice just to preserve gender.
KOKORO_SET_VOICES = (
    "voices/em_alex.pt",      # Spanish male
    "voices/hm_omega.pt",    # Hindi male
    "voices/im_nicola.pt",   # Italian male
    "voices/jm_kumo.pt",     # Japanese male
    "voices/pm_alex.pt",     # Portuguese male
    "voices/zm_yunyang.pt",  # Mandarin male
)

PIPER_SET_VOICES = (
    "fr/fr_FR/tom/medium/fr_FR-tom-medium.onnx",                   # French male
    "de/de_DE/kerstin/low/de_DE-kerstin-low.onnx",                # German female
    "ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx",              # Russian female
    "pl/pl_PL/mc_speech/medium/pl_PL-mc_speech-medium.onnx",      # Polish male
    "uk/uk_UA/tetiana/high/uk_UA-tetiana-high.onnx",              # Ukrainian female
    "uk/uk_UA/mykyta/high/uk_UA-mykyta-high.onnx",                # Ukrainian male
)

CORE = ("de", "ko", "ar", "ru")
ALL_COMMON = tuple(PIPER_COMMON)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Explicitly download optional local voices used by TALUS multilingual routing."
    )
    group = p.add_mutually_exclusive_group()
    group.add_argument("--core", action="store_true", help="German, Korean, Arabic, Russian")
    group.add_argument("--all", action="store_true", help="All configured common-language Piper voices")
    group.add_argument("--voice-sets", action="store_true", help="Extra male/female counterparts used by the dashboard voice sets")
    group.add_argument("--complete", action="store_true", help="All common-language voices plus all voice-set counterparts")
    p.add_argument(
        "languages",
        nargs="*",
        choices=ALL_COMMON,
        help="Specific common-language codes to download (for example: de ko ar)",
    )
    return p.parse_args()


def _download_piper(hf_hub_download, model: str) -> None:
    target = ROOT / "models" / "piper"
    target.mkdir(parents=True, exist_ok=True)
    for filename in (model, model + ".json"):
        path = hf_hub_download(repo_id=PIPER_REPO_ID, filename=filename, local_dir=target)
        print(f"        {path}")


def _download_kokoro(hf_hub_download, filename: str) -> None:
    target = ROOT / "models" / "kokoro"
    target.mkdir(parents=True, exist_ok=True)
    path = hf_hub_download(repo_id=KOKORO_REPO_ID, filename=filename, local_dir=target)
    print(f"        {path}")


def main() -> int:
    args = parse_args()
    try:
        from huggingface_hub import hf_hub_download
    except ImportError as exc:
        raise SystemExit(
            "huggingface_hub is not installed. Run: python -m pip install -r requirements.txt"
        ) from exc

    common: tuple[str, ...] = ()
    include_sets = False
    if args.complete:
        common = ALL_COMMON
        include_sets = True
    elif args.voice_sets:
        include_sets = True
    elif args.all:
        common = ALL_COMMON
    elif args.core:
        common = CORE
    elif args.languages:
        common = tuple(args.languages)
    else:
        common = CORE

    for language in common:
        model = PIPER_COMMON[language]
        print(f"[VOICE] common/{language}: {model}")
        _download_piper(hf_hub_download, model)

    if include_sets:
        for filename in KOKORO_SET_VOICES:
            print(f"[VOICE] set/Kokoro: {filename}")
            _download_kokoro(hf_hub_download, filename)
        for model in PIPER_SET_VOICES:
            print(f"[VOICE] set/Piper: {model}")
            _download_piper(hf_hub_download, model)

    print("\nDone. Verify with: python tools\\check_models.py")
    if include_sets:
        print("Japanese note: full Misaki Japanese G2P also needs the UniDic dictionary.")
        print("If check_models reports it missing, run: python -m unidic download")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
