"""OpenAI-compatible /chat/completions transport, standard library only.

Used by app/core/llm.py when LLM_PROVIDER=nim (NVIDIA NIM, Isoquant or any compatible endpoint)
or LLM_PROVIDER=openai (api.openai.com, with its parameter differences handled below). Two
limits apply to every request: a sliding window of NIM_MAX_RPM (OPENAI_MAX_RPM) per minute
and at most NIM_MAX_CONCURRENT (OPENAI_MAX_CONCURRENT) in flight (the free endpoints
answer 429 to bursts of parallel requests well below the per-minute limit). Rate limits, server
errors and timeouts are retried with backoff; a 429 honours Retry-After and backs off longer.
Tests replace the transport with `set_transport`.
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from collections.abc import Callable
from typing import Any

from app.core.config import get_settings

RETRY_STATUS = {408, 429, 500, 502, 503, 504}
BACKOFF_S = (3, 10, 30)
BACKOFF_429_S = (15, 30, 60, 120, 240)


class NimError(RuntimeError):
    pass


class RateLimiter:
    """Sliding-window limit on requests per minute, shared by all threads."""

    def __init__(
        self,
        max_per_minute: int,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.max = max(1, max_per_minute)
        self._clock, self._sleep = clock, sleep
        self._sent: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = self._clock()
                while self._sent and now - self._sent[0] >= 60:
                    self._sent.popleft()
                if len(self._sent) < self.max:
                    self._sent.append(now)
                    return
                wait = 60 - (now - self._sent[0])
            self._sleep(wait + 0.05)


_limiter: RateLimiter | None = None
_limiter_lock = threading.Lock()
_inflight: threading.BoundedSemaphore | None = None


def inflight() -> threading.BoundedSemaphore:
    global _inflight
    with _limiter_lock:
        if _inflight is None:
            _inflight = threading.BoundedSemaphore(max(1, get_settings().chat_max_concurrent))
        return _inflight


def limiter() -> RateLimiter:
    global _limiter
    with _limiter_lock:
        if _limiter is None:
            _limiter = RateLimiter(get_settings().chat_max_rpm)
        return _limiter


Transport = Callable[[dict[str, Any]], dict[str, Any]]
_transport: Transport | None = None


def set_transport(fn: Transport | None) -> None:
    global _transport
    _transport = fn


def _http_post(body: dict[str, Any]) -> dict[str, Any]:
    s = get_settings()
    if not s.chat_api_key:
        raise NimError(
            "no API key for the chat endpoint (OPENAI_API_KEY, NVIDIA_API_KEY or ISOQUANT_API_KEY)"
        )
    headers = {
        "Authorization": f"Bearer {s.chat_api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if s.is_isoquant:
        headers["Isoquant-ZDR"] = "required"  # zero data retention: prompts are not stored
    req = urllib.request.Request(
        s.chat_base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    last: Exception | None = None
    attempt = limited = 0
    while True:
        limiter().acquire()  # every attempt counts against the per-minute limit
        retry_after: float | None = None
        with inflight():
            try:
                with urllib.request.urlopen(req, timeout=s.nim_timeout_s) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")[:300]
                if e.code not in RETRY_STATUS:
                    raise NimError(f"NIM HTTP {e.code}: {detail}") from e
                last = NimError(f"NIM HTTP {e.code}: {detail}")
                if e.code == 429:
                    try:
                        retry_after = float(e.headers.get("Retry-After") or "")
                    except ValueError:
                        retry_after = None
            except (TimeoutError, urllib.error.URLError) as e:
                last = e
        if retry_after is not None or "HTTP 429" in str(last):
            if limited >= len(BACKOFF_429_S):
                break
            time.sleep(max(retry_after or 0, BACKOFF_429_S[limited]))
            limited += 1
            continue
        if attempt >= len(BACKOFF_S):
            break
        time.sleep(BACKOFF_S[attempt])
        attempt += 1
    raise NimError(f"NIM request failed after retries: {last}")


def chat(body: dict[str, Any]) -> dict[str, Any]:
    return (_transport or _http_post)(body)


_OPENAI_REASONING = re.compile(r"^(?:openai/)?(?:o\d|gpt-5)", re.I)


def is_openai_reasoning(model: str) -> bool:
    """OpenAI reasoning models (o-series, gpt-5 family): no temperature, `reasoning_effort`."""
    return _OPENAI_REASONING.match(model) is not None


def thinking_options(off: bool, model: str = "") -> dict[str, Any]:
    """Request fields that turn a reasoning model's thinking off (or keep it brief)."""
    s = get_settings()
    if s.is_openai:
        # Other OpenAI models reject `reasoning_effort`; reasoning models keep their default
        # unless the caller wants thinking off.
        if off and is_openai_reasoning(model):
            return {"reasoning_effort": s.openai_reasoning_effort_off}
        return {}
    if s.is_isoquant:
        return {"reasoning_effort": "none" if off else "low"}
    return {"chat_template_kwargs": {"enable_thinking": False}} if off else {}


def build_body(
    *,
    model: str,
    system: str | None,
    messages: list[dict[str, str]],
    max_tokens: int,
    json_mode: bool,
) -> dict[str, Any]:
    msgs = ([{"role": "system", "content": system}] if system else []) + messages
    body: dict[str, Any] = {
        "model": model,
        "messages": msgs,
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    if get_settings().is_openai:
        # OpenAI: `max_tokens` is deprecated in favour of `max_completion_tokens` (which also
        # covers reasoning tokens), and reasoning models reject any temperature but the
        # default. Reproducibility then comes from the disk cache, as with Anthropic.
        body["max_completion_tokens"] = body.pop("max_tokens")
        if is_openai_reasoning(model):
            body.pop("temperature")
            body["max_completion_tokens"] = max(
                body["max_completion_tokens"], get_settings().openai_reasoning_min_tokens
            )
    return body


_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I)


def message_text(resp: dict[str, Any]) -> tuple[str, str | None]:
    """Return (content without reasoning, finish_reason)."""
    choice = (resp.get("choices") or [{}])[0]
    content = (choice.get("message") or {}).get("content") or ""
    return _THINK.sub("", content).strip(), choice.get("finish_reason")


def extract_json(text: str) -> Any:
    t = _FENCE.sub("", text.strip()).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        start, end = t.find("{"), t.rfind("}")
        if start == -1 or end <= start:
            raise
        return json.loads(t[start : end + 1])


def usage(resp: dict[str, Any]) -> tuple[int, int]:
    u = resp.get("usage") or {}
    return int(u.get("prompt_tokens") or 0), int(u.get("completion_tokens") or 0)


def schema_instruction(schema: dict[str, Any]) -> str:
    return (
        "Respond with one JSON object only, no prose and no code fences. It must validate "
        "against this JSON Schema:\n" + json.dumps(schema, ensure_ascii=False)
    )
