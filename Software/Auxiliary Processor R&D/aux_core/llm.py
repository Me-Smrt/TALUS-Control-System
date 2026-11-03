from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import threading
import time
from pathlib import Path
from typing import Any, Iterable, Iterator

from .util import data_url_jpeg


class LlmError(RuntimeError):
    pass


class OpenAICompatibleLlm:
    """OpenAI-compatible client with fast/deep Qwen reasoning profiles."""

    def __init__(self, cfg: dict[str, Any], root: Path | None = None, runtime_system_context: str | None = None):
        self.cfg = dict(cfg)
        self.root = Path(root or Path.cwd())
        self.base = str(cfg.get("base_url", "http://127.0.0.1:8000/v1")).rstrip("/")
        self.model = str(cfg.get("model", "Qwen/Qwen3.5-4B"))
        self.api_key = os.getenv(str(cfg.get("api_key_env", "AUTOMATON_LLM_API_KEY")), "").strip()
        self.runtime_system_context = str(runtime_system_context or "").strip()

        default_temperature = float(cfg.get("temperature", 0.55))
        default_max_tokens = int(cfg.get("max_tokens", 1024))
        default_timeout = float(cfg.get("timeout_s", 60.0))
        profiles = dict(cfg.get("profiles", {}))
        self.profiles = {
            "fast": {
                "temperature": default_temperature,
                "max_tokens": default_max_tokens,
                "timeout_s": default_timeout,
                "reasoning_effort": "none",
                "auto_continue_on_length": 1,
                **dict(profiles.get("fast", {})),
            },
            "deep": {
                "temperature": 0.45,
                "max_tokens": 4096,
                "timeout_s": 300.0,
                "reasoning_effort": "high",
                "auto_continue_on_length": 1,
                **dict(profiles.get("deep", {})),
            },
        }
        self.system_prompt = self._load_system_prompt(cfg)
        self._metrics_lock = threading.RLock()
        self._turn_calls: list[dict[str, Any]] = []

    def _load_system_prompt(self, cfg: dict[str, Any]) -> str:
        configured_file = str(cfg.get("system_prompt_file", "")).strip()
        if configured_file:
            p = Path(configured_file)
            p = p if p.is_absolute() else (self.root / p).resolve()
            if p.is_file():
                return self._expand_system_prompt(p.read_text(encoding="utf-8").strip())
        return self._expand_system_prompt(str(cfg.get("system_prompt", "")).strip())

    def _expand_system_prompt(self, prompt: str) -> str:
        marker = "{{RUNTIME_CAPABILITIES}}"
        runtime = self.runtime_system_context
        if marker in prompt:
            return prompt.replace(marker, runtime or "RUNTIME CAPABILITY INVENTORY: unavailable for this process.").strip()
        if runtime:
            return f"{prompt}\n\n{runtime}".strip()
        return prompt.strip()


    def begin_turn_metrics(self) -> None:
        with self._metrics_lock:
            self._turn_calls = []

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        # Used only when an OpenAI-compatible backend omits usage metadata.
        # The dashboard labels the source so estimated counts are never confused
        # with backend-reported token counts.
        value = str(text or "")
        return max(1, round(len(value) / 4)) if value else 0

    def _record_call_metrics(
        self,
        *,
        started: float,
        ended: float,
        first_token_at: float | None,
        text: str,
        finish_reason: str | None,
        usage: dict[str, Any] | None = None,
        timings: dict[str, Any] | None = None,
        streamed: bool,
    ) -> None:
        usage = dict(usage or {})
        timings = dict(timings or {})
        completion = usage.get("completion_tokens")
        prompt = usage.get("prompt_tokens")
        source = "api" if completion is not None else "estimated"
        try:
            completion = int(completion) if completion is not None else self._estimate_tokens(text)
        except Exception:
            completion = self._estimate_tokens(text)
            source = "estimated"
        try:
            prompt = int(prompt) if prompt is not None else None
        except Exception:
            prompt = None
        total_ms = max(0.0, (ended - started) * 1000.0)
        ttft_ms = ((first_token_at - started) * 1000.0) if first_token_at is not None else None
        generation_start = first_token_at if first_token_at is not None else started
        generation_s = max(0.001, ended - generation_start)
        backend_tps = timings.get("predicted_per_second") or timings.get("tokens_per_second")
        try:
            tps = float(backend_tps) if backend_tps is not None else (completion / generation_s if completion else None)
        except Exception:
            tps = completion / generation_s if completion else None
        row = {
            "streamed": bool(streamed),
            "total_ms": round(total_ms, 2),
            "ttft_ms": round(ttft_ms, 2) if ttft_ms is not None else None,
            "completion_tokens": completion,
            "prompt_tokens": prompt,
            "tokens_per_second": round(tps, 3) if tps is not None else None,
            "token_count_source": source,
            "finish_reason": finish_reason,
        }
        with self._metrics_lock:
            self._turn_calls.append(row)

    def end_turn_metrics(self) -> dict[str, Any]:
        with self._metrics_lock:
            calls = list(self._turn_calls)
        if not calls:
            return {}
        completion = sum(int(x.get("completion_tokens") or 0) for x in calls)
        prompt_values = [x.get("prompt_tokens") for x in calls if x.get("prompt_tokens") is not None]
        total_ms = sum(float(x.get("total_ms") or 0.0) for x in calls)
        generation_seconds = 0.0
        for x in calls:
            call_ms = float(x.get("total_ms") or 0.0)
            ttft = float(x.get("ttft_ms") or 0.0) if x.get("ttft_ms") is not None else 0.0
            generation_seconds += max(0.001, (call_ms - ttft) / 1000.0)
        sources = {str(x.get("token_count_source")) for x in calls}
        return {
            "calls": len(calls),
            "total_ms": round(total_ms, 2),
            "ttft_ms": calls[0].get("ttft_ms"),
            "completion_tokens": completion,
            "prompt_tokens": sum(int(x) for x in prompt_values) if prompt_values else None,
            "tokens_per_second": round(completion / generation_seconds, 3) if completion else None,
            "token_count_source": "api" if sources == {"api"} else "estimated" if sources == {"estimated"} else "mixed",
            "finish_reason": calls[-1].get("finish_reason"),
        }

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            h["Authorization"] = "Bearer " + self.api_key
        return h

    def _profile(self, reasoning_mode: str) -> dict[str, Any]:
        mode = str(reasoning_mode or "fast").lower()
        if mode not in self.profiles:
            raise LlmError("reasoning_mode must be 'fast' or 'deep'")
        return dict(self.profiles[mode])

    @staticmethod
    def _budget_instruction(max_tokens: int) -> str:
        return (
            f"You have a finite generation budget of at most {int(max_tokens)} tokens for this turn. "
            "Budget the answer so it reaches a complete conclusion. Prefer a concise complete answer over an unfinished long one. "
            "Do not intentionally stop in the middle of a sentence; if space is becoming tight, summarize remaining details and conclude naturally. "
            "Do not narrate private scratch work, false starts, or self-corrections in the user-facing answer. "
            "If you notice an error while solving, correct it silently before presenting the answer. "
            "For quantitative work, verify the governing formula, units, arithmetic, and any node/variable mapping before giving the final result."
        )

    def _payload(
        self,
        messages: list[dict[str, Any]],
        *,
        image_jpeg: bytes | None = None,
        extra_prompt: str | None = None,
        reasoning_mode: str = "fast",
        stream: bool = False,
    ) -> tuple[dict[str, Any], float]:
        profile = self._profile(reasoning_mode)
        max_tokens = int(profile.get("max_tokens", 1024))
        msgs: list[dict[str, Any]] = []
        # Keep exactly one system message. Some llama.cpp/Qwen chat templates reject
        # multiple system-role messages with a server-side template error (HTTP 500).
        # Fold per-turn generation guidance into the configured TALUS system prompt
        # instead of adding a second system message.
        system_parts = [x for x in (self.system_prompt, self._budget_instruction(max_tokens)) if x]
        if system_parts:
            msgs.append({"role": "system", "content": "\n\n".join(system_parts)})
        msgs.extend(messages)

        if image_jpeg is not None:
            if not msgs or msgs[-1].get("role") != "user":
                msgs.append({"role": "user", "content": "Describe the image."})
            text = msgs[-1].get("content", "")
            if not isinstance(text, str):
                text = json.dumps(text, ensure_ascii=False)
            if extra_prompt:
                text = f"{extra_prompt}\n\n{text}" if text else extra_prompt
            msgs[-1] = {
                "role": "user",
                "content": [
                    {"type": "text", "text": text},
                    {"type": "image_url", "image_url": {"url": data_url_jpeg(image_jpeg)}},
                ],
            }
        elif extra_prompt and msgs:
            text = msgs[-1].get("content", "")
            if not isinstance(text, str):
                text = json.dumps(text, ensure_ascii=False)
            msgs[-1] = {"role": "user", "content": f"{extra_prompt}\n\n{text}"}

        deep = reasoning_mode == "deep"
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": msgs,
            "temperature": float(profile.get("temperature", 0.55)),
            "max_tokens": max_tokens,
            "stream": bool(stream),
            "reasoning_effort": str(profile.get("reasoning_effort", "high" if deep else "none")),
            "chat_template_kwargs": {"enable_thinking": bool(deep)},
        }
        return payload, float(profile.get("timeout_s", 60.0))

    def _post_json(self, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        req = urllib.request.Request(
            self.base + "/chat/completions",
            data=json.dumps(payload).encode(),
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            # urllib's default string hides llama.cpp's useful JSON/body error.
            # Surface it so template/parameter compatibility problems are actually
            # diagnosable from the console instead of appearing as a bare HTTP 500.
            try:
                detail = e.read().decode("utf-8", errors="replace").strip()
            except Exception:
                detail = ""
            msg = f"HTTP {e.code}: {e.reason}"
            if detail:
                msg += f" -- {detail[:4000]}"
            raise LlmError(msg) from e
        except Exception as e:
            raise LlmError(str(e)) from e

    @staticmethod
    def _choice_text(body: dict[str, Any]) -> tuple[str, str | None, bool]:
        try:
            choice = body["choices"][0]
            message = choice["message"]
            content = message.get("content", "")
            if content is None:
                content = ""
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False)
            return content.strip(), choice.get("finish_reason"), bool(message.get("reasoning_content"))
        except Exception as e:
            raise LlmError(f"Unexpected LLM response shape: {body!r}") from e

    @staticmethod
    def _continuation_instruction() -> str:
        return (
            "Continue exactly where your previous answer was cut off. Finish the current sentence first, then complete the answer concisely. "
            "Do not repeat material that was already stated. End at a natural sentence boundary."
        )

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        image_jpeg: bytes | None = None,
        extra_prompt: str | None = None,
        reasoning_mode: str = "fast",
    ) -> str:
        current_messages = list(messages)
        combined = ""
        attempts = 0
        while True:
            profile = self._profile(reasoning_mode)
            payload, timeout = self._payload(
                current_messages,
                image_jpeg=image_jpeg,
                extra_prompt=extra_prompt,
                reasoning_mode=reasoning_mode,
                stream=False,
            )
            call_started = time.perf_counter()
            body = self._post_json(payload, timeout)
            call_ended = time.perf_counter()
            content, finish, had_reasoning = self._choice_text(body)
            self._record_call_metrics(
                started=call_started, ended=call_ended, first_token_at=None, text=content,
                finish_reason=finish, usage=body.get("usage"), timings=body.get("timings"), streamed=False,
            )
            if content:
                combined = (combined + content).strip()
            elif had_reasoning:
                raise LlmError(
                    "The model produced reasoning but no final answer. Increase the deep profile token/context budget or retry in fast mode."
                )
            else:
                raise LlmError(f"The model returned an empty final answer (finish_reason={finish!r}).")

            limit = max(0, int(profile.get("auto_continue_on_length", 1)))
            if finish != "length" or attempts >= limit:
                return combined
            attempts += 1
            current_messages = list(messages) + [
                {"role": "assistant", "content": combined},
                {"role": "user", "content": self._continuation_instruction()},
            ]

    def _stream_once(self, payload: dict[str, Any], timeout: float) -> Iterator[str]:
        """Yield final-answer chunks; StopIteration.value is finish_reason."""
        req = urllib.request.Request(
            self.base + "/chat/completions",
            data=json.dumps(payload).encode(),
            headers=self._headers(),
            method="POST",
        )
        finish_reason = None
        usage: dict[str, Any] = {}
        timings: dict[str, Any] = {}
        parts: list[str] = []
        started = time.perf_counter()
        first_token_at = None
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                for raw in r:
                    line = raw.decode("utf-8", errors="ignore").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                        if isinstance(obj.get("usage"), dict):
                            usage = dict(obj["usage"])
                        if isinstance(obj.get("timings"), dict):
                            timings = dict(obj["timings"])
                        choices = obj.get("choices") or []
                        if not choices:
                            continue
                        choice = choices[0]
                        if choice.get("finish_reason") is not None:
                            finish_reason = choice.get("finish_reason")
                        delta = choice.get("delta", {})
                        chunk = delta.get("content")
                        # reasoning_content is deliberately ignored.
                        if chunk:
                            if first_token_at is None:
                                first_token_at = time.perf_counter()
                            value = str(chunk)
                            parts.append(value)
                            yield value
                    except Exception:
                        continue
        except urllib.error.HTTPError as e:
            try:
                detail = e.read().decode("utf-8", errors="replace").strip()
            except Exception:
                detail = ""
            msg = f"HTTP {e.code}: {e.reason}"
            if detail:
                msg += f" -- {detail[:4000]}"
            raise LlmError(msg) from e
        except Exception as e:
            raise LlmError(str(e)) from e
        finally:
            ended = time.perf_counter()
            self._record_call_metrics(
                started=started, ended=ended, first_token_at=first_token_at, text="".join(parts),
                finish_reason=finish_reason, usage=usage, timings=timings, streamed=True,
            )
        return finish_reason

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        *,
        image_jpeg: bytes | None = None,
        extra_prompt: str | None = None,
        reasoning_mode: str = "fast",
    ) -> Iterable[str]:
        """Stream only final-answer text, automatically continuing one length-cut response."""
        current_messages = list(messages)
        combined = ""
        attempts = 0
        while True:
            profile = self._profile(reasoning_mode)
            payload, timeout = self._payload(
                current_messages,
                image_jpeg=image_jpeg,
                extra_prompt=extra_prompt,
                reasoning_mode=reasoning_mode,
                stream=True,
            )
            gen = self._stream_once(payload, timeout)
            finish = None
            turn_parts: list[str] = []
            while True:
                try:
                    chunk = next(gen)
                except StopIteration as stop:
                    finish = stop.value
                    break
                turn_parts.append(chunk)
                combined += chunk
                yield chunk

            limit = max(0, int(profile.get("auto_continue_on_length", 1)))
            if finish != "length" or attempts >= limit:
                break
            attempts += 1
            current_messages = list(messages) + [
                {"role": "assistant", "content": combined.strip()},
                {"role": "user", "content": self._continuation_instruction()},
            ]


class MockLlm:
    def begin_turn_metrics(self):
        self._metric_started = time.perf_counter()

    def end_turn_metrics(self):
        started = getattr(self, "_metric_started", time.perf_counter())
        return {"calls": 1, "total_ms": round((time.perf_counter()-started)*1000, 2), "ttft_ms": 0.0, "completion_tokens": None, "prompt_tokens": None, "tokens_per_second": None, "token_count_source": "mock", "finish_reason": "stop"}

    def chat(self, messages, **kwargs):
        text = str(messages[-1].get("content", "")) if messages else ""
        mode = kwargs.get("reasoning_mode", "fast")
        return f"Mock {mode} response: {text}".strip()

    def stream_chat(self, messages, **kwargs):
        reply = self.chat(messages, **kwargs)
        midpoint = max(1, len(reply) // 2)
        yield reply[:midpoint]
        if midpoint < len(reply):
            yield reply[midpoint:]
