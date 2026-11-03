from __future__ import annotations

import os
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


class LlmServerError(RuntimeError):
    pass


class ManagedLlamaServer:
    """Owns an optional local llama.cpp OpenAI-compatible server process.

    The manager first probes the configured API.  If a healthy server already
    exists it is reused and left running on shutdown.  Otherwise, when
    ``auto_start`` is enabled, a local llama.cpp executable is launched with the
    configured GGUF model + multimodal projector and is terminated with this
    process.
    """

    def __init__(self, root: Path, llm_cfg: dict[str, Any]):
        self.root = Path(root)
        self.llm_cfg = dict(llm_cfg)
        self.cfg = dict(self.llm_cfg.get("managed_server", {}))
        self.base_url = str(self.llm_cfg.get("base_url", "http://127.0.0.1:8000/v1")).rstrip("/")
        parsed = urllib.parse.urlparse(self.base_url)
        self.host = str(self.cfg.get("host") or parsed.hostname or "127.0.0.1")
        self.port = int(self.cfg.get("port") or parsed.port or (443 if parsed.scheme == "https" else 80))
        self.process: subprocess.Popen | None = None
        self._log_handle = None
        self.owns_process = False

    def _resolve_path(self, value: str | Path) -> Path:
        p = Path(value).expanduser()
        return p if p.is_absolute() else (self.root / p).resolve()

    @property
    def health_url(self) -> str:
        # llama.cpp exposes /health and /v1/health.  Because our base URL ends
        # in /v1, this keeps API configuration and health probing in sync.
        return self.base_url + "/health"

    def healthy(self, timeout: float = 0.75) -> bool:
        try:
            req = urllib.request.Request(self.health_url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return int(getattr(response, "status", 200)) == 200
        except (urllib.error.URLError, TimeoutError, OSError):
            return False

    def _find_executable(self) -> tuple[str, bool]:
        """Return (executable, needs_serve_subcommand)."""
        configured = str(self.cfg.get("executable", "auto") or "auto").strip()
        env_override = os.getenv("AUTOMATON_LLAMA_SERVER", "").strip()
        candidates: list[str] = []
        if env_override:
            candidates.append(env_override)
        if configured.lower() != "auto":
            candidates.append(configured)

        # Prefer a runtime bundled beside this project.  This keeps laptop/Windows
        # development self-contained and avoids requiring users to modify PATH.
        #
        # The project root passed by main.py is the directory containing main.py,
        # so these resolve to:
        #   <project>/runtime/llama-server.exe
        #   <project>/runtime/llama-server
        # and, for newer unified llama.cpp builds:
        #   <project>/runtime/llama.exe
        #   <project>/runtime/llama
        candidates.extend([
            "runtime/llama-server.exe",
            "runtime/llama-server",
            "runtime/llama.exe",
            "runtime/llama",
        ])

        # Finally fall back to the user's PATH.
        candidates.extend(["llama-server", "llama-server.exe", "llama", "llama.exe"])

        seen: set[str] = set()
        for candidate in candidates:
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            p = Path(candidate).expanduser()
            found: str | None = None
            if p.is_absolute() or p.parent != Path('.'):
                rp = p if p.is_absolute() else (self.root / p).resolve()
                if rp.is_file():
                    found = str(rp)
            else:
                found = shutil.which(candidate)
            if found:
                name = Path(found).name.lower()
                return found, name in {"llama", "llama.exe"}

        raise LlmServerError(
            "Could not find llama.cpp's llama-server executable. Put a llama.cpp build "
            "in this project's runtime/ directory, put llama-server on PATH, set "
            "llm.managed_server.executable in config/default.json, or set "
            "AUTOMATON_LLAMA_SERVER to the executable path."
        )


    def _resolve_model_candidate(self, configured: str | Path, filename: str) -> Path:
        """Resolve a configured model path, with defensive project-local fallbacks.

        Preferred order:
          1. configured path exactly as written
          2. models/qwen/<filename>
          3. models/<filename>
          4. recursive search under models/ for an exact filename match

        This keeps startup tolerant of moving the Qwen pair one directory deeper
        or shallower without silently selecting a different model filename.
        """
        configured_path = self._resolve_path(configured)
        if configured_path.is_file():
            return configured_path

        candidates = [
            (self.root / "models" / "qwen" / filename).resolve(),
            (self.root / "models" / filename).resolve(),
        ]
        for candidate in candidates:
            if candidate.is_file():
                return candidate

        models_root = (self.root / "models").resolve()
        if models_root.is_dir():
            matches = [m.resolve() for m in models_root.rglob(filename) if m.is_file()]
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                raise LlmServerError(
                    f"Multiple copies of {filename} were found under {models_root}. "
                    f"Set the exact path in config/default.json. Matches: "
                    + ", ".join(str(m) for m in matches)
                )

        return configured_path

    def _build_command(self) -> list[str]:
        exe, needs_serve = self._find_executable()
        model = self._resolve_model_candidate(
            str(self.cfg.get("model_path", "models/qwen/Qwen3.5-4B-Q4_K_M.gguf")),
            "Qwen3.5-4B-Q4_K_M.gguf",
        )
        mmproj = self._resolve_model_candidate(
            str(self.cfg.get("mmproj_path", "models/qwen/mmproj-Qwen3.5-4B-BF16.gguf")),
            "mmproj-Qwen3.5-4B-BF16.gguf",
        )
        if not model.is_file():
            raise LlmServerError(f"Qwen GGUF model not found: {model}")
        if not mmproj.is_file():
            raise LlmServerError(f"Qwen multimodal projector not found: {mmproj}")

        cmd = [exe]
        if needs_serve:
            cmd.append("serve")
        cmd += [
            "--model", str(model),
            "--mmproj", str(mmproj),
            "--host", self.host,
            "--port", str(self.port),
            "--alias", str(self.llm_cfg.get("model", "Qwen/Qwen3.5-4B")),
            "--ctx-size", str(int(self.cfg.get("context_size", 4096))),
            "--parallel", str(int(self.cfg.get("parallel", 1))),
            "--n-gpu-layers", str(self.cfg.get("gpu_layers", "auto")),
        ]
        # Current llama.cpp expects an explicit value for --flash-attn:
        #   --flash-attn on|off|auto
        # Keep backwards compatibility with our earlier boolean config while
        # preferring the string form going forward.
        flash_cfg = self.cfg.get("flash_attention", "auto")
        if isinstance(flash_cfg, bool):
            flash_value = "on" if flash_cfg else "off"
        else:
            flash_value = str(flash_cfg or "auto").strip().lower()
            if flash_value not in {"on", "off", "auto"}:
                raise LlmServerError(
                    "llm.managed_server.flash_attention must be one of "
                    "'on', 'off', or 'auto' (or a legacy boolean)."
                )
        cmd += ["--flash-attn", flash_value]

        # Qwen3.5 is a hybrid reasoning model. Run llama.cpp in hybrid/auto mode so individual requests can choose
        # fast non-thinking or deep reasoning through the OpenAI request body.
        # Current llama.cpp exposes this as --reasoning on|off|auto.
        reasoning_value = str(self.cfg.get("reasoning", "auto") or "auto").strip().lower()
        if reasoning_value not in {"on", "off", "auto"}:
            raise LlmServerError(
                "llm.managed_server.reasoning must be one of 'on', 'off', or 'auto'."
            )
        cmd += ["--reasoning", reasoning_value]

        for arg in self.cfg.get("extra_args", []) or []:
            cmd.append(str(arg))
        return cmd

    def ensure_ready(self, *, verbose: bool = True) -> str:
        """Reuse a healthy external server or start and wait for our own.

        ``verbose=False`` is used by the production/deployment entrypoint so
        normal model startup does not pollute stdout. Errors still raise in the
        normal way and llama.cpp output remains in its runtime log file.
        """
        if self.healthy():
            self.owns_process = False
            return "external"
        if not bool(self.cfg.get("auto_start", True)):
            raise LlmServerError(
                f"LLM server is not responding at {self.health_url} and automatic startup is disabled."
            )

        command = self._build_command()
        log_path = self._resolve_path(str(self.cfg.get("log_path", "runtime/llama-server.log")))
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_handle = log_path.open("a", encoding="utf-8", buffering=1)
        self._log_handle.write("\n=== Automaton launching llama.cpp ===\n")
        self._log_handle.write("Command: " + subprocess.list2cmdline(command) + "\n")

        creationflags = 0
        if os.name == "nt" and hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
        self.process = subprocess.Popen(
            command,
            cwd=str(self.root),
            stdout=self._log_handle,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
        self.owns_process = True

        deadline = time.monotonic() + float(self.cfg.get("startup_timeout_s", 120.0))
        next_message = 0.0
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                code = self.process.returncode
                self.stop()
                raise LlmServerError(
                    f"llama.cpp server exited during startup with code {code}. See {log_path}"
                )
            if self.healthy(timeout=1.0):
                return "managed"
            now = time.monotonic()
            if now >= next_message:
                if verbose:
                    print("[AUX] Waiting for Qwen/llama.cpp to finish loading...")
                next_message = now + 2.0
            time.sleep(0.2)

        self.stop()
        raise LlmServerError(
            f"Timed out waiting for llama.cpp at {self.health_url}. See {log_path}"
        )

    def stop(self) -> None:
        """Stop only a server process launched by this manager."""
        if self.process is not None and self.owns_process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.process.kill()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    pass
        self.process = None
        self.owns_process = False
        if self._log_handle is not None:
            try:
                self._log_handle.close()
            except Exception:
                pass
            self._log_handle = None
