from __future__ import annotations
import html, importlib.util, io, math, os, re, shutil, struct, subprocess, tempfile, wave, warnings
from pathlib import Path
from typing import Any

from .language import detect_text_language, split_text_language_spans


class NoSpeakableText(RuntimeError):
    """A streamed formatting fragment contained no useful speech payload."""


class VoiceSetUnavailable(RuntimeError):
    """The active strict voice set has no installed voice for this language."""

    def __init__(self, voice_set_id: str, language: str | None):
        self.voice_set_id = str(voice_set_id or "")
        self.language = str(language or "und")
        super().__init__(
            f"voice_set_unavailable:{self.voice_set_id}:{self.language}"
        )


def _has_speakable_text(text: str) -> bool:
    value = str(text or "").strip()
    if not value or not any(ch.isalnum() for ch in value):
        return False
    # Streaming can occasionally isolate a Markdown/list label fragment such as
    # ``d:`` while a language name is arriving token-by-token. Do not send that
    # fragment to Piper; some voice models return an empty WAV for it.
    if re.fullmatch(r"[A-Za-z][A-Za-z ._-]{0,20}\s*[:;]", value):
        return False
    return True


def _quiet_kokoro_warnings():
    """Suppress known third-party deprecation/config warnings only."""
    ctx = warnings.catch_warnings()
    ctx.__enter__()
    warnings.filterwarnings("ignore", message=r"dropout option adds dropout.*", category=UserWarning)
    warnings.filterwarnings("ignore", message=r".*torch\.nn\.utils\.weight_norm.*deprecated.*", category=FutureWarning)
    warnings.filterwarnings("ignore", message=r".*torch\.jit\.script.*deprecated.*", category=FutureWarning)
    return ctx





_GREEK_WORDS = {
    r"\\alpha": "alpha", r"\\beta": "beta", r"\\gamma": "gamma", r"\\delta": "delta",
    r"\\Delta": "delta", r"\\theta": "theta", r"\\lambda": "lambda", r"\\mu": "mu",
    r"\\pi": "pi", r"\\rho": "rho", r"\\sigma": "sigma", r"\\Sigma": "sigma",
    r"\\phi": "phi", r"\\omega": "omega", r"\\Omega": "ohms",
}


def _extract_braced(text: str, start: int) -> tuple[str, int] | None:
    """Return the content/end index for a balanced {...} group."""
    if start >= len(text) or text[start] != "{":
        return None
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1:i], i + 1
    return None


def _space_subscript(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9]+", " ", value).strip()
    if len(value) <= 4 and " " not in value:
        return " ".join(value)
    return value


def _verbalize_math(expr: str, *, max_chars: int = 420, _depth: int = 0) -> str:
    """Conservatively convert common LaTeX/math into speech-friendly prose.

    Display text is never changed. This is only for the TTS copy. Common
    engineering formulas (fractions, subscripts, powers, Greek letters and
    arithmetic operators) are verbalized. Very large/structured expressions
    fall back to a short screen-reference rather than reading punctuation.
    """
    raw = str(expr or "").strip()
    if not raw:
        return ""
    if len(raw) > max_chars or re.search(r"\\begin\s*\{|\\end\s*\{|\\matrix|\\cases", raw):
        return "The full equation is shown on screen."
    if _depth > 6:
        return "the displayed expression"

    x = raw.replace("\n", " ")
    x = x.replace(r"\left", "").replace(r"\right", "")

    # Whitespace between mathematical atoms generally means multiplication.
    # Do this before expanding fractions so already-verbalized words are never
    # mistaken for adjacent math symbols.
    if _depth == 0:
        x = re.sub(r"(?<=[A-Za-z0-9_}\)])\s+(?=[A-Za-z\\(])", " times ", x)

    # Expand \frac{numerator}{denominator} and \sqrt{...} using balanced groups.
    def expand_command(src: str, command: str, two_groups: bool) -> str:
        pos = 0
        out = []
        while True:
            idx = src.find(command, pos)
            if idx < 0:
                out.append(src[pos:])
                break
            out.append(src[pos:idx])
            j = idx + len(command)
            while j < len(src) and src[j].isspace():
                j += 1
            first = _extract_braced(src, j)
            if not first:
                out.append(command)
                pos = j
                continue
            a, end1 = first
            if two_groups:
                k = end1
                while k < len(src) and src[k].isspace():
                    k += 1
                second = _extract_braced(src, k)
                if not second:
                    out.append(command)
                    pos = j
                    continue
                b, end2 = second
                left = _verbalize_math(a, max_chars=max_chars, _depth=_depth + 1)
                right = _verbalize_math(b, max_chars=max_chars, _depth=_depth + 1)
                out.append(f" {left} divided by the quantity {right} ")
                pos = end2
            else:
                left = _verbalize_math(a, max_chars=max_chars, _depth=_depth + 1)
                out.append(f" square root of {left} ")
                pos = end1
        return "".join(out)

    # Repeated passes handle nested fractions from the inside out reasonably well.
    for _ in range(4):
        before = x
        x = expand_command(x, r"\frac", True)
        x = expand_command(x, r"\sqrt", False)
        if x == before:
            break

    # Subscripts/superscripts before braces are discarded.
    x = re.sub(
        r"([A-Za-z])_\{([^{}]+)\}",
        lambda m: f"{m.group(1)} sub {_space_subscript(m.group(2))}",
        x,
    )
    x = re.sub(r"([A-Za-z])_([A-Za-z0-9]+)", lambda m: f"{m.group(1)} sub {_space_subscript(m.group(2))}", x)
    x = re.sub(r"([A-Za-z0-9)]+)\^\{?2\}?", r"\1 squared", x)
    x = re.sub(r"([A-Za-z0-9)]+)\^\{?3\}?", r"\1 cubed", x)
    x = re.sub(r"([A-Za-z0-9)]+)\^\{?([^{}\s]+)\}?", r"\1 to the power of \2", x)

    for symbol, word in _GREEK_WORDS.items():
        x = x.replace(symbol, f" {word} ")
    x = x.replace("Δ", " delta ").replace("Ω", " ohms ").replace("π", " pi ")

    commands = {
        r"\times": " times ", r"\cdot": " times ", r"\pm": " plus or minus ",
        r"\approx": " approximately ", r"\neq": " not equal to ", r"\leq": " less than or equal to ",
        r"\le": " less than or equal to ", r"\geq": " greater than or equal to ", r"\ge": " greater than or equal to ",
        r"\infty": " infinity ", r"\sum": " the sum ", r"\int": " the integral ",
    }
    for symbol, word in commands.items():
        x = x.replace(symbol, word)

    # Remaining common operators. Slash is only used when a model wrote plain
    # math rather than \frac; braces are presentation-only by this point.
    x = x.replace("=", " equals ")
    x = x.replace("+", " plus ")
    x = re.sub(r"(?<![Ee])-", " minus ", x)
    x = x.replace("*", " times ")
    x = x.replace("/", " divided by ")
    x = x.replace("{", " ").replace("}", " ")
    x = x.replace("_", " sub ")
    # Unknown LaTeX commands are read as their command name, not "backslash...".
    x = re.sub(r"\\([A-Za-z]+)", lambda m: " " + m.group(1).replace("operatorname", "") + " ", x)
    x = re.sub(r"\s+", " ", x).strip()
    return x


def _normalize_math_for_speech(text: str, *, mode: str = "auto", max_chars: int = 420) -> str:
    if str(mode).lower() in {"off", "false", "none"}:
        # Still remove delimiter punctuation so TTS never says "dollar dollar".
        return str(text).replace("$$", " ").replace("$", " ")

    s = str(text)
    repl = lambda m: "\n" + _verbalize_math(m.group(1), max_chars=max_chars) + "\n"
    # Display forms first, then inline forms.
    s = re.sub(r"\$\$(.+?)\$\$", repl, s, flags=re.DOTALL)
    s = re.sub(r"\\\[(.+?)\\\]", repl, s, flags=re.DOTALL)
    s = re.sub(r"\\\((.+?)\\\)", lambda m: _verbalize_math(m.group(1), max_chars=max_chars), s, flags=re.DOTALL)
    s = re.sub(r"(?<!\\)\$(?!\$)(.+?)(?<!\\)\$", lambda m: _verbalize_math(m.group(1), max_chars=max_chars), s, flags=re.DOTALL)
    # Unicode math that appears outside explicit delimiters should still sound sane.
    s = s.replace("Δ", " delta ").replace("Ω", " ohms ")
    return s


def prepare_text_for_speech(
    text: str,
    *,
    speak_code: bool = False,
    speak_urls: bool = False,
    math_mode: str = "auto",
    math_max_chars: int = 420,
) -> str:
    """Convert display-oriented Markdown into natural text for TTS.

    The original LLM response remains untouched for terminal/dashboard display.
    Only the copy sent to the speech backend is normalized. This prevents
    literal readings such as "asterisk asterisk" while retaining useful
    sentence/list content.
    """
    if not text:
        return ""
    s = html.unescape(str(text)).replace('\r\n', '\n').replace('\r', '\n')
    s = _normalize_math_for_speech(s, mode=math_mode, max_chars=int(math_max_chars))

    # Fenced code is useful on-screen but usually awful when spoken.
    def _code_block(match: re.Match[str]) -> str:
        body = (match.group(1) or '').strip()
        if speak_code and body:
            return '\n' + body + '\n'
        return '\nCode example omitted from speech.\n' if body else '\n'
    s = re.sub(r'```(?:[^\n`]*)\n?(.*?)```', _code_block, s, flags=re.DOTALL)

    # Images disappear; Markdown links keep their human-readable label.
    s = re.sub(r'!\[([^\]]*)\]\([^)]*\)', r'\1', s)
    s = re.sub(r'\[([^\]]+)\]\((?:[^()]|\([^)]*\))*\)', r'\1', s)

    # Bare URLs are generally not useful to pronounce character-by-character.
    if speak_urls:
        s = re.sub(r'https?://\S+', lambda m: m.group(0).rstrip('.,;:!?'), s)
    else:
        s = re.sub(r'https?://\S+', ' link ', s)

    # Strip common Markdown/HTML structure while preserving the words.
    s = re.sub(r'<[^>]+>', ' ', s)
    s = re.sub(r'^\s{0,3}#{1,6}\s*', '', s, flags=re.MULTILINE)
    s = re.sub(r'^\s*>+\s?', '', s, flags=re.MULTILINE)
    s = re.sub(r'^\s*[-+*]\s+', '', s, flags=re.MULTILINE)
    s = re.sub(r'^\s*(\d+)[.)]\s+', r'\1. ', s, flags=re.MULTILINE)
    s = re.sub(r'^\s*[-*_]{3,}\s*$', ' ', s, flags=re.MULTILINE)

    # Inline code keeps the code text but loses backticks. Emphasis markers and
    # strikethrough markers are presentation, not spoken content.
    s = re.sub(r'`([^`]+)`', r'\1', s)
    s = s.replace('**', '').replace('__', '').replace('~~', '')
    s = re.sub(r'(?<!\w)[*_](?=\S)|(?<=\S)[*_](?!\w)', '', s)

    # Tables become short pauses rather than "pipe" characters.
    s = re.sub(r'\s*\|\s*', '; ', s)
    s = re.sub(r'^\s*:?-{3,}:?(?:\s*;\s*:?-{3,}:?)+\s*$', ' ', s, flags=re.MULTILINE)

    # Remove remaining Markdown escapes and formatting punctuation that TTS
    # engines sometimes verbalize literally. Keep normal prose punctuation.
    s = re.sub(r'\\([`*_{}\[\]()#+.!>~-])', r'\1', s)
    s = s.replace('•', '. ').replace('▪', '. ').replace('◦', '. ')

    lines = [re.sub(r'[ \t]+', ' ', line).strip() for line in s.split('\n')]
    spoken_lines = []
    for line in lines:
        if not line:
            continue
        # Markdown commonly uses one visual line per bullet/paragraph. Give a
        # line that has no terminal punctuation a sentence boundary, but do
        # not create awkward combinations such as "Try this:.".
        if line[-1] not in '.!?;:':
            line += '.'
        spoken_lines.append(line)
    s = ' '.join(spoken_lines)
    s = re.sub(r'\.{2,}', '.', s)
    s = re.sub(r'\s+([,.;:!?])', r'\1', s)
    s = re.sub(r'([.!?])(?=[A-Za-z])', r'\1 ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s

class TtsBackend:
    def available(self,voice:dict[str,Any])->bool: return True
    def warmup(self,voice:dict[str,Any])->None: return None
    def synthesize(self,text:str,voice:dict[str,Any],speed:float=1.0)->bytes: raise NotImplementedError

class MockToneBackend(TtsBackend):
    def synthesize(self,text,voice,speed=1.0):
        sr=16000; dur=max(.2,min(1.0,len(text)/80)); frames=int(sr*dur); out=io.BytesIO()
        with wave.open(out,'wb') as w:
            w.setnchannels(1);w.setsampwidth(2);w.setframerate(sr)
            for i in range(frames):
                val=int(2500*math.sin(2*math.pi*440*i/sr)); w.writeframesraw(struct.pack('<h',val))
        return out.getvalue()

class KokoroLocalBackend(TtsBackend):
    def __init__(self,cfg:dict[str,Any],root:Path):
        self.root=root; p=Path(str(cfg.get("model_dir","models/kokoro"))); self.dir=p if p.is_absolute() else (root/p).resolve(); self.device=str(cfg.get("device","auto")); self._model=None; self._pipelines={}
    def _paths(self,voice):
        return self.dir/'config.json', self.dir/'kokoro-v1_0.pth', self.dir/str(voice.get('voice_file',f"voices/{voice['voice']}.pt"))
    def available(self,voice):
        c,m,v=self._paths(voice)
        deps = importlib.util.find_spec('kokoro') is not None and importlib.util.find_spec('torch') is not None
        return deps and c.is_file() and m.is_file() and v.is_file()
    def _load(self,voice):
        if importlib.util.find_spec('kokoro') is None:
            raise RuntimeError("Kokoro Python package is not installed. Run: pip install -r requirements.txt")
        if importlib.util.find_spec('torch') is None:
            raise RuntimeError("PyTorch is required by Kokoro. Run: pip install -r requirements.txt")
        c,m,v=self._paths(voice)
        if not (c.is_file() and m.is_file() and v.is_file()):
            raise RuntimeError(f"Kokoro assets missing for {voice['id']} under {self.dir}")
        quiet = _quiet_kokoro_warnings()
        try:
            from kokoro import KModel, KPipeline
            import torch
            if self._model is None:
                dev=('cuda' if torch.cuda.is_available() else 'cpu') if self.device=='auto' else self.device
                self._model=KModel(repo_id='hexgrad/Kokoro-82M',config=str(c),model=str(m)).to(dev).eval()
            lang=str(voice.get('lang_code','a'))
            if lang not in self._pipelines:
                self._pipelines[lang]=KPipeline(lang_code=lang,model=self._model,repo_id='hexgrad/Kokoro-82M',device=str(self._model.device))
            return self._pipelines[lang], str(v)
        finally:
            quiet.__exit__(None, None, None)
    def warmup(self,voice):
        self._load(voice)

    def synthesize(self,text,voice,speed=1.0):
        import numpy as np
        pipe,vpath=self._load(voice); chunks=[]
        quiet = _quiet_kokoro_warnings()
        try:
            for result in pipe(text,voice=vpath,speed=float(speed)):
                if result.audio is not None: chunks.append(result.audio.detach().cpu().numpy())
        finally:
            quiet.__exit__(None, None, None)
        if not chunks: raise RuntimeError('Kokoro produced no audio')
        audio=np.concatenate(chunks); pcm=(np.clip(audio,-1,1)*32767).astype(np.int16).tobytes(); out=io.BytesIO()
        with wave.open(out,'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(24000);w.writeframes(pcm)
        return out.getvalue()

class PiperCliBackend(TtsBackend):
    def __init__(self,cfg:dict[str,Any],root:Path):self.binary=str(cfg.get('binary','piper'));self.root=root
    def available(self,voice):
        p=Path(str(voice.get('model_path',''))); p=p if p.is_absolute() else self.root/p
        config_raw=str(voice.get('config_path','')).strip()
        c=Path(config_raw) if config_raw else None
        if c is not None and not c.is_absolute(): c=self.root/c
        config_ok = True if c is None else c.is_file()
        return shutil.which(self.binary) is not None and p.is_file() and config_ok
    @staticmethod
    def _describe_voice(voice: dict[str, Any]) -> str:
        vid = str(voice.get("id", "unknown_voice"))
        language = str(voice.get("language", "und"))
        return f"{vid} ({language})"

    @staticmethod
    def _validate_wav(path: Path) -> tuple[int, int, int]:
        try:
            with wave.open(str(path), "rb") as wav_file:
                channels = int(wav_file.getnchannels())
                frames = int(wav_file.getnframes())
                rate = int(wav_file.getframerate())
        except Exception as exc:
            raise RuntimeError(f"Piper did not produce a valid WAV: {exc}") from exc
        if channels <= 0 or frames <= 0 or rate <= 0:
            raise RuntimeError(
                f"Piper produced an empty WAV (channels={channels}, frames={frames}, rate={rate})"
            )
        return channels, frames, rate

    def synthesize(self,text,voice,speed=1.0):
        p=Path(str(voice['model_path'])); p=p if p.is_absolute() else (self.root/p).resolve()
        if not self.available(voice): raise RuntimeError(f'Piper unavailable or model missing: {p}')
        clean_text = str(text or "").strip()
        if not _has_speakable_text(clean_text):
            raise NoSpeakableText('No speakable Piper text remained after normalization')
        with tempfile.NamedTemporaryFile(suffix='.wav',delete=False) as tmp: outp=Path(tmp.name)
        try:
            # Piper's Python CLI reads redirected stdin through TextIOWrapper.
            # On native Windows that wrapper can inherit a legacy ANSI encoding
            # even though TALUS writes UTF-8 bytes to the pipe. This is especially
            # visible with Cyrillic (Russian voices): the child can decode invalid
            # bytes with surrogate escapes and later crash while re-encoding them.
            # Force UTF-8 mode only for the Piper child process so the rest of the
            # TALUS/Windows environment remains untouched.
            child_env = os.environ.copy()
            # Native Windows Python can decode redirected stdin using a legacy
            # code page.  Force UTF-8 only for the Piper child on Windows.
            # Linux/Jetson keeps its normal environment and remains the primary
            # deployment path.
            if os.name == 'nt':
                child_env['PYTHONUTF8'] = '1'
                child_env['PYTHONIOENCODING'] = 'utf-8'
            proc=subprocess.run(
                [self.binary,'--model',str(p),'--output_file',str(outp)],
                input=(clean_text + "\n").encode('utf-8'),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
                env=child_env,
            )
            if proc.returncode!=0:
                detail=proc.stderr.decode(errors='ignore').strip()[-1200:]
                snippet=re.sub(r"\s+", " ", clean_text)[:120]
                raise RuntimeError(
                    f"Piper synthesis failed for {self._describe_voice(voice)} "
                    f"while speaking {snippet!r}: {detail or f'exit code {proc.returncode}'}"
                )
            try:
                self._validate_wav(outp)
            except RuntimeError as exc:
                snippet=re.sub(r"\s+", " ", clean_text)[:120]
                raise RuntimeError(
                    f"Piper synthesis failed for {self._describe_voice(voice)} "
                    f"while speaking {snippet!r}: {exc}"
                ) from exc
            return outp.read_bytes()
        finally: outp.unlink(missing_ok=True)

class TtsManager:
    def __init__(self, cfg, registry, root):
        self.cfg = cfg
        self.registry = registry
        self.root = root
        self.backends = {}
        routing = dict(cfg.get('language_routing', {}))
        self.auto_language = bool(routing.get('enabled', True))
        self.language_confidence = float(routing.get('min_confidence', 0.80))
        self.language_switch_confidence = float(routing.get('switch_min_confidence', 0.95))
        self.language_switch_min_words = int(routing.get('switch_min_words', 4))
        self.inherit_short_latin_from_hint = bool(routing.get('inherit_short_latin_from_hint', True))
        for name, b in cfg.get('backends', {}).items():
            typ = b.get('type')
            if typ == 'kokoro_local':
                self.backends[name] = KokoroLocalBackend(b, root)
            elif typ == 'piper_cli':
                self.backends[name] = PiperCliBackend(b, root)
            elif typ == 'mock_tone':
                self.backends[name] = MockToneBackend()

    def voice_status(self, voice):
        backend = self.backends.get(voice.get('backend'))
        return bool(backend and backend.available(voice))

    def list_voices(self):
        out = []
        for voice in self.registry.all():
            item = dict(voice)
            item['available'] = self.voice_status(voice)
            item['active'] = voice['id'] == self.registry.active_id
            out.append(item)
        return out

    def _configured_language_families(self):
        from .util import language_family
        families = set()
        for voice in self.registry.all():
            for language in voice.get('languages', []):
                fam = language_family(language)
                if fam and fam != 'und':
                    families.add(fam)
        return families

    def _first_available(self, candidates):
        for voice in candidates:
            backend = self.backends.get(voice.get('backend'))
            if backend and backend.available(voice):
                return voice, backend
        return None, None

    def _select_voice(self, language=None, *, voice_id=None, voice_set_id=None):
        candidates = self.registry.candidates_for_language(
            language, preferred_id=voice_id, voice_set_id=voice_set_id
        )
        voice, backend = self._first_available(candidates)
        if voice is not None:
            return voice, backend

        selected_set_id = voice_set_id if voice_set_id is not None else self.registry.active_set_id
        if (
            voice_id is None
            and selected_set_id
            and self.registry.voice_set_fallback_policy(selected_set_id) == 'strict'
        ):
            from .util import language_family
            raise VoiceSetUnavailable(selected_set_id, language_family(language))

        # Last-resort compatibility fallback. Prefer the correct language, then
        # any installed voice rather than failing the whole utterance.
        from .util import language_family
        fam = language_family(language)
        ordered = self.registry.all()
        ordered.sort(
            key=lambda v: 0
            if (
                fam == 'und'
                or fam in [language_family(x) for x in v.get('languages', [])]
                or '*' in v.get('languages', [])
            )
            else 1
        )
        voice, backend = self._first_available(ordered)
        if voice is None or backend is None:
            requested = voice_id or voice_set_id or self.registry.active_set_id or self.registry.active_id
            raise RuntimeError(f'Selected TTS voice/set is unavailable: {requested}')
        return voice, backend

    def list_voice_sets(self):
        """Return dashboard-friendly set coverage based on installed assets."""
        families = sorted(self._configured_language_families())
        out = []
        for voice_set in self.registry.all_sets():
            sid = voice_set['id']
            exact = 0
            usable = 0
            language_rows = {}
            for fam in families:
                exact_candidates = self.registry.set_candidates_for_language(sid, fam)
                exact_voice, _ = self._first_available(exact_candidates)
                try:
                    selected_voice, _ = self._select_voice(fam, voice_set_id=sid)
                except VoiceSetUnavailable:
                    selected_voice = None
                is_exact = exact_voice is not None and selected_voice is not None and selected_voice['id'] == exact_voice['id']
                if exact_voice is not None:
                    exact += 1
                if selected_voice is not None:
                    usable += 1
                language_rows[fam] = {
                    'voice_id': selected_voice.get('id') if selected_voice else None,
                    'display_name': selected_voice.get('display_name') if selected_voice else None,
                    'exact_set_match': bool(is_exact),
                }
            item = dict(voice_set)
            item.update({
                'active': sid == self.registry.active_set_id,
                'exact_language_count': exact,
                'available_language_count': usable,
                'total_language_count': len(families),
                'languages': language_rows,
            })
            out.append(item)
        return out

    def resolve_language(self, text, *, hint=None, voice_id=None, auto_language=None):
        """Choose language from the text that will actually be spoken."""
        if voice_id is not None:
            return hint
        enabled = self.auto_language if auto_language is None else bool(auto_language)
        if not enabled:
            return hint
        detected, _confidence = detect_text_language(
            str(text),
            hint=hint,
            candidates=self._configured_language_families(),
            min_confidence=self.language_confidence,
            switch_min_confidence=self.language_switch_confidence,
            switch_min_words=self.language_switch_min_words,
            inherit_short_latin_from_hint=self.inherit_short_latin_from_hint,
        )
        return detected or hint

    def segment_text_by_language(self, text, *, hint=None, voice_id=None, auto_language=None):
        """Return ordered (text, language) spans for streaming TTS."""
        if voice_id is not None:
            return [(str(text).strip(), hint)] if str(text).strip() else []
        enabled = self.auto_language if auto_language is None else bool(auto_language)
        routing = dict(self.cfg.get('language_routing', {}))
        if not enabled or not bool(routing.get('segment_mixed_chunks', True)):
            language = self.resolve_language(text, hint=hint, auto_language=enabled)
            return [(str(text).strip(), language)] if str(text).strip() else []
        return split_text_language_spans(
            str(text),
            hint=hint,
            candidates=self._configured_language_families(),
            min_confidence=self.language_confidence,
            switch_min_confidence=self.language_switch_confidence,
            switch_min_words=self.language_switch_min_words,
            inherit_short_latin_from_hint=self.inherit_short_latin_from_hint,
        )

    def warmup(self, *, voice_id=None, voice_set_id=None, language=None):
        voice, backend = self._select_voice(
            language, voice_id=voice_id, voice_set_id=voice_set_id
        )
        backend.warmup(voice)
        return voice

    def synthesize(
        self,
        text,
        *,
        voice_id=None,
        voice_set_id=None,
        language=None,
        speed=None,
        auto_language=None,
    ):
        routed_language = self.resolve_language(
            text, hint=language, voice_id=voice_id, auto_language=auto_language
        )
        voice, backend = self._select_voice(
            routed_language, voice_id=voice_id, voice_set_id=voice_set_id
        )
        speech_cfg = self.cfg.get('speech_text', {})
        spoken = prepare_text_for_speech(
            text,
            speak_code=bool(speech_cfg.get('speak_code', False)),
            speak_urls=bool(speech_cfg.get('speak_urls', False)),
            math_mode=str(speech_cfg.get('math_mode', 'auto')),
            math_max_chars=int(speech_cfg.get('math_max_chars', 420)),
        ) if speech_cfg.get('sanitize_markdown', True) else str(text)
        if not _has_speakable_text(spoken):
            raise NoSpeakableText('No speakable text remained after TTS normalization')
        return backend.synthesize(
            spoken,
            voice,
            float(speed if speed is not None else self.cfg.get('speed', 1.0)),
        ), voice

