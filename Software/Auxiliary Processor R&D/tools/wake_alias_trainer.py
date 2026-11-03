from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aux_core.stt import FasterWhisperStt


WORD_RE = re.compile(r"[^\W_]+(?:['’][^\W_]+)?", re.UNICODE)
SUPPORTED_AUDIO = {".wav", ".flac", ".ogg", ".aiff", ".aif"}


def _levenshtein(a: str, b: str) -> int:
    a, b = str(a), str(b)
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        for j, cb in enumerate(b, start=1):
            cur.append(min(cur[-1] + 1, prev[j] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _norm_token(text: str) -> str:
    tokens = WORD_RE.findall(str(text or ""))
    if not tokens:
        return ""
    return tokens[0].casefold()


def _best_token(text: str, target: str) -> str:
    tokens = [t.casefold() for t in WORD_RE.findall(str(text or ""))]
    if not tokens:
        return ""
    tgt = target.casefold()
    return min(tokens, key=lambda t: (_levenshtein(t, tgt), abs(len(t) - len(tgt))))


def _similarity(candidate: str, target: str) -> float:
    if not candidate and not target:
        return 1.0
    denom = max(len(candidate), len(target), 1)
    return max(0.0, 1.0 - (_levenshtein(candidate.casefold(), target.casefold()) / denom))


def _load_cfg() -> dict:
    return json.loads((ROOT / "config" / "default.json").read_text(encoding="utf-8"))


def _existing_aliases(cfg: dict, target: str) -> set[str]:
    eng = cfg.get("engagement", {}) or {}
    vals = {target.casefold()}
    vals.update(str(v).strip().casefold() for v in eng.get("wake_name_aliases", []) if str(v).strip())
    return vals


def _analyze(rows: list[dict], target: str, existing: set[str], min_share: float, min_count: int) -> dict:
    usable = [r for r in rows if r.get("candidate")]
    counts = Counter(r["candidate"] for r in usable)
    n = len(usable)
    required = max(int(min_count), int(math.ceil(max(n, 1) * float(min_share))))

    suggestions = []
    for candidate, count in counts.most_common():
        sim = _similarity(candidate, target)
        if candidate in existing or candidate == target.casefold():
            continue
        if count >= required and sim >= 0.45:
            suggestions.append({
                "alias": candidate,
                "count": count,
                "share": count / max(n, 1),
                "similarity": sim,
            })

    last_q_start = int(math.floor(n * 0.75))
    prior = {r["candidate"] for r in usable[:last_q_start]}
    recent = {r["candidate"] for r in usable[last_q_start:]}
    new_recent = sorted(x for x in recent if x not in prior)

    exact = sum(1 for r in usable if r["candidate"] == target.casefold())
    mean_similarity = statistics.fmean(r["similarity"] for r in usable) if usable else 0.0
    mean_edit_distance = statistics.fmean(r["edit_distance"] for r in usable) if usable else 0.0
    mean_language_probability = statistics.fmean(r["language_probability"] for r in usable) if usable else 0.0
    mean_transcription_s = statistics.fmean(r["transcription_s"] for r in usable) if usable else 0.0

    # Categorical strings have no meaningful arithmetic mean.  We therefore
    # report the mode/frequency distribution and numerical means of distance,
    # similarity and confidence.
    mode = counts.most_common(1)[0] if counts else ("", 0)
    likely_enough = n >= 20 and len(new_recent) <= 1

    return {
        "target": target,
        "samples": len(rows),
        "usable_samples": n,
        "exact_rate": exact / max(n, 1),
        "mode": {"text": mode[0], "count": mode[1], "share": mode[1] / max(n, 1)},
        "mean_similarity": mean_similarity,
        "mean_edit_distance": mean_edit_distance,
        "mean_language_probability": mean_language_probability,
        "mean_transcription_s": mean_transcription_s,
        "distribution": [
            {
                "text": text,
                "count": count,
                "share": count / max(n, 1),
                "similarity": _similarity(text, target),
                "existing_alias": text in existing,
            }
            for text, count in counts.most_common()
        ],
        "suggested_aliases": suggestions,
        "new_variants_in_last_quarter": new_recent,
        "sample_size_assessment": (
            "20 samples are probably sufficient for the current environment; no substantial new alias tail appeared late."
            if likely_enough
            else "Collect more samples if you want higher confidence; the alias distribution is still changing or fewer than 20 usable samples were collected."
        ),
    }


def _profile_slug(name: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9._-]+", "_", str(name or "default").strip()).strip("._-")
    return value or "default"


def _profile_root() -> Path:
    return ROOT / "runtime" / "wake_alias_training" / "profiles"


def _profile_report_path(name: str) -> Path:
    return _profile_root() / _profile_slug(name) / "report.json"


def _write_report(out_dir: Path, rows: list[dict], summary: dict, existing: set[str], profile: str = "default") -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "automaton.wake_alias_training.v1",
        "generated_at": time.time(),
        "hotword_bias_disabled": True,
        "profile": _profile_slug(profile),
        "summary": summary,
        "existing_aliases": sorted(existing),
        "samples": rows,
    }
    json_path = out_dir / "wake_alias_training_latest.json"
    md_path = out_dir / "wake_alias_training_latest.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# TALUS Wake Alias Training Report",
        "",
        f"Target: **{summary['target']}**",
        f"Usable samples: **{summary['usable_samples']} / {summary['samples']}**",
        f"Exact TALUS rate: **{summary['exact_rate']:.1%}**",
        f"Most common transcription: **{summary['mode']['text'] or '(none)'}** ({summary['mode']['share']:.1%})",
        f"Mean normalized spelling similarity: **{summary['mean_similarity']:.3f}**",
        f"Mean edit distance: **{summary['mean_edit_distance']:.3f} characters**",
        f"Mean STT language confidence: **{summary['mean_language_probability']:.1%}**",
        f"Mean transcription time: **{summary['mean_transcription_s']:.3f} s**",
        "",
        "> A word/string does not have a meaningful arithmetic mean. The trainer therefore uses the mode/frequency distribution plus numerical means for edit distance, similarity, confidence, and latency.",
        "",
        "## Distribution",
        "",
        "| Transcription | Count | Share | Similarity | Existing alias |",
        "|---|---:|---:|---:|:---:|",
    ]
    for item in summary["distribution"]:
        lines.append(
            f"| `{item['text']}` | {item['count']} | {item['share']:.1%} | {item['similarity']:.3f} | {'yes' if item['existing_alias'] else 'no'} |"
        )
    lines += ["", "## Suggested new aliases", ""]
    if summary["suggested_aliases"]:
        for item in summary["suggested_aliases"]:
            lines.append(
                f"- `{item['alias']}` — {item['count']} samples ({item['share']:.1%}), similarity {item['similarity']:.3f}"
            )
    else:
        lines.append("- None from this run.")

    proposed = sorted(existing | {s["alias"] for s in summary["suggested_aliases"]})
    lines += [
        "",
        "## Proposed wake-name aliases",
        "",
        "```json",
        json.dumps(proposed, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Sample-size assessment",
        "",
        summary["sample_size_assessment"],
        "",
        f"New variants first seen in the final quarter: {', '.join(summary['new_variants_in_last_quarter']) or 'none'}",
        "",
        "Aliases are suggestions only. This tool never edits config/default.json automatically.",
    ]
    markdown = "\n".join(lines) + "\n"
    md_path.write_text(markdown, encoding="utf-8")

    profile_dir = _profile_root() / _profile_slug(profile)
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "report.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (profile_dir / "report.md").write_text(markdown, encoding="utf-8")
    return json_path, md_path


def _load_profile(name: str) -> dict:
    path = _profile_report_path(name)
    if not path.exists():
        raise FileNotFoundError(f"Wake profile not found: {name!r} ({path})")
    return json.loads(path.read_text(encoding="utf-8"))


def _compare_profiles(names: list[str], primary: str | None = None) -> dict:
    payloads = [(_profile_slug(name), _load_profile(name)) for name in names]
    primary_slug = _profile_slug(primary) if primary else (payloads[-1][0] if payloads else None)
    rows = []
    alias_scores: dict[str, float] = {}
    alias_sources: dict[str, list[str]] = {}
    for slug, payload in payloads:
        summary = payload.get("summary", {}) or {}
        rows.append({
            "profile": slug,
            "samples": int(summary.get("usable_samples", 0) or 0),
            "exact_rate": float(summary.get("exact_rate", 0.0) or 0.0),
            "mode": (summary.get("mode") or {}).get("text", ""),
            "mean_similarity": float(summary.get("mean_similarity", 0.0) or 0.0),
            "suggested_aliases": [x.get("alias") for x in summary.get("suggested_aliases", []) if x.get("alias")],
        })
        weight = 2.0 if slug == primary_slug else 1.0
        for item in summary.get("suggested_aliases", []):
            alias = str(item.get("alias", "")).strip().casefold()
            if not alias:
                continue
            share = float(item.get("share", 0.0) or 0.0)
            alias_scores[alias] = alias_scores.get(alias, 0.0) + weight * share
            alias_sources.setdefault(alias, []).append(slug)
    recommendations = [
        {"alias": alias, "weighted_score": score, "profiles": alias_sources.get(alias, [])}
        for alias, score in sorted(alias_scores.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    return {
        "schema": "automaton.wake_alias_profile_comparison.v1",
        "generated_at": time.time(),
        "primary_profile": primary_slug,
        "profiles": rows,
        "recommended_alias_union": recommendations,
    }


def _write_comparison(payload: dict) -> tuple[Path, Path]:
    root = ROOT / "runtime" / "wake_alias_training"
    root.mkdir(parents=True, exist_ok=True)
    json_path = root / "comparison_latest.json"
    md_path = root / "comparison_latest.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# TALUS Wake Alias Profile Comparison",
        "",
        f"Primary/final-hardware profile: **{payload.get('primary_profile') or '(none)'}**",
        "",
        "| Profile | Samples | Exact TALUS | Mode | Mean similarity | Suggested aliases |",
        "|---|---:|---:|---|---:|---|",
    ]
    for row in payload.get("profiles", []):
        aliases = ", ".join(f"`{x}`" for x in row.get("suggested_aliases", [])) or "none"
        lines.append(
            f"| {row['profile']} | {row['samples']} | {row['exact_rate']:.1%} | `{row['mode']}` | {row['mean_similarity']:.3f} | {aliases} |"
        )
    lines += ["", "## Recommended alias union", ""]
    recs = payload.get("recommended_alias_union", [])
    if recs:
        for item in recs:
            lines.append(
                f"- `{item['alias']}` — weighted score {item['weighted_score']:.3f}; seen in {', '.join(item['profiles'])}"
            )
    else:
        lines.append("- No new aliases were recommended by the compared profiles.")
    lines += [
        "",
        "The primary profile receives double weight so the final robot microphone/environment can dominate development-laptop observations.",
    ]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def _record_samples(count: int, duration: float, sample_rate: int, keep_audio: bool, root: Path) -> list[Path]:
    import numpy as np
    import sounddevice as sd
    import soundfile as sf

    root.mkdir(parents=True, exist_ok=True)
    files = []
    print(f"[WAKE TRAIN] Recording {count} sample(s), {duration:.2f}s each at {sample_rate} Hz.")
    print("[WAKE TRAIN] Press Enter for each sample, say only TALUS naturally, then stay quiet until capture ends.")
    for i in range(1, count + 1):
        input(f"[{i:02d}/{count:02d}] Press Enter when ready...")
        print("  recording...", flush=True)
        audio = sd.rec(int(duration * sample_rate), samplerate=sample_rate, channels=1, dtype="float32")
        sd.wait()
        arr = np.asarray(audio, dtype=np.float32).reshape(-1)
        path = root / f"talus_{i:03d}.wav"
        sf.write(str(path), arr, sample_rate, subtype="PCM_16")
        files.append(path)
        print(f"  saved {path.name}")
    return files


def _audio_files(folder: Path, limit: int | None) -> list[Path]:
    files = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.casefold() in SUPPORTED_AUDIO)
    return files[:limit] if limit else files


def parse_args():
    p = argparse.ArgumentParser(description="Train/evaluate TALUS wake-name STT aliases from real recordings.")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--record", action="store_true", help="Interactively record samples from the configured/default microphone.")
    src.add_argument("--audio-dir", type=Path, help="Analyze existing real recordings in a folder.")
    src.add_argument("--compare-profiles", nargs="+", metavar="PROFILE", help="Compare previously saved named microphone/environment profiles.")
    p.add_argument("--profile", default="default", help="Name for this microphone/environment profile (for example laptop_mic or usb_mic_robot_installed).")
    p.add_argument("--primary-profile", help="When comparing profiles, double-weight this profile (normally the final robot microphone).")
    p.add_argument("--trials", type=int, default=20, help="Number of samples to record/analyze (default: 20).")
    p.add_argument("--target", default="TALUS", help="Canonical wake name (default: TALUS).")
    p.add_argument("--language", default="en", help="Whisper language hint for the wake-name samples (default: en).")
    p.add_argument("--duration", type=float, default=1.5, help="Recording duration per trial in seconds (default: 1.5).")
    p.add_argument("--sample-rate", type=int, default=16000, help="Recording sample rate (default: 16000).")
    p.add_argument("--keep-audio", action="store_true", help="Keep newly recorded WAV files under the named profile directory.")
    p.add_argument("--min-share", type=float, default=0.10, help="Minimum sample share for an alias suggestion (default: 0.10).")
    p.add_argument("--min-count", type=int, default=2, help="Minimum absolute count for an alias suggestion (default: 2).")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.compare_profiles:
        try:
            comparison = _compare_profiles(args.compare_profiles, primary=args.primary_profile)
        except FileNotFoundError as exc:
            raise SystemExit(str(exc)) from exc
        json_path, md_path = _write_comparison(comparison)
        print(f"[WAKE TRAIN] Comparison JSON: {json_path}")
        print(f"[WAKE TRAIN] Comparison Markdown: {md_path}")
        return 0

    if args.trials <= 0:
        raise SystemExit("--trials must be greater than zero")

    cfg = _load_cfg()
    stt = FasterWhisperStt(cfg.get("stt", {}), ROOT)
    if not stt.available():
        raise SystemExit(f"STT model not found: {stt.path}")

    runtime = ROOT / "runtime" / "telemetry"
    cleanup_tmp = None
    if args.record:
        if args.keep_audio:
            audio_root = _profile_root() / _profile_slug(args.profile) / "audio"
        else:
            cleanup_tmp = tempfile.TemporaryDirectory(prefix="talus-wake-")
            audio_root = Path(cleanup_tmp.name)
        files = _record_samples(args.trials, args.duration, args.sample_rate, args.keep_audio, audio_root)
    else:
        folder = args.audio_dir.resolve()
        if not folder.is_dir():
            raise SystemExit(f"Audio folder not found: {folder}")
        files = _audio_files(folder, args.trials)

    if not files:
        raise SystemExit("No supported audio files found.")

    print(f"[WAKE TRAIN] Transcribing {len(files)} real sample(s) with hotword bias DISABLED...")
    rows = []
    target = args.target.strip() or "TALUS"
    for i, path in enumerate(files, start=1):
        started = time.perf_counter()
        out = stt.transcribe(path, language=args.language or None, use_config_hotwords=False)
        elapsed = time.perf_counter() - started
        transcript = str(out.get("text", "") or "").strip()
        candidate = _best_token(transcript, target)
        dist = _levenshtein(candidate.casefold(), target.casefold()) if candidate else len(target)
        sim = _similarity(candidate, target)
        row = {
            "index": i,
            "file": path.name,
            "transcript": transcript,
            "candidate": candidate,
            "language": out.get("language"),
            "language_probability": float(out.get("language_probability", 0.0) or 0.0),
            "edit_distance": dist,
            "similarity": sim,
            "transcription_s": elapsed,
        }
        rows.append(row)
        print(
            f"[{i:02d}/{len(files):02d}] {transcript!r} -> alias={candidate!r} "
            f"sim={sim:.3f} conf={row['language_probability']:.0%}"
        )

    existing = _existing_aliases(cfg, target)
    summary = _analyze(rows, target, existing, args.min_share, args.min_count)
    json_path, md_path = _write_report(runtime, rows, summary, existing, profile=args.profile)

    print(f"\n[WAKE TRAIN] Summary (profile={_profile_slug(args.profile)})")
    print(f"  exact TALUS rate : {summary['exact_rate']:.1%}")
    print(f"  mode             : {summary['mode']['text']!r} ({summary['mode']['share']:.1%})")
    print(f"  mean similarity  : {summary['mean_similarity']:.3f}")
    print(f"  mean edit dist.  : {summary['mean_edit_distance']:.3f}")
    print(f"  suggestions      : {', '.join(x['alias'] for x in summary['suggested_aliases']) or 'none'}")
    print(f"  assessment       : {summary['sample_size_assessment']}")
    print(f"[WAKE TRAIN] JSON report: {json_path}")
    print(f"[WAKE TRAIN] Markdown report: {md_path}")

    if cleanup_tmp is not None:
        cleanup_tmp.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
