"""NVIDIA NIM transport (OpenAI-compatible /chat/completions), standard library only.

Used by app/core/llm.py when LLM_PROVIDER=nim. Retries rate limits, server errors and
timeouts with backoff. Tests replace the transport with `set_transport`.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from app.core.config import get_settings

RETRY_STATUS = {408, 429, 500, 502, 503, 504}
BACKOFF_S = (3, 10, 30)


class NimError(RuntimeError):
    pass


Transport = Callable[[dict[str, Any]], dict[str, Any]]
_transport: Transport | None = None


def set_transport(fn: Transport | None) -> None:
    global _transport
    _transport = fn


def _http_post(body: dict[str, Any]) -> dict[str, Any]:
    s = get_settings()
    if not s.nvidia_api_key:
        raise NimError("NVIDIA_API_KEY is not set")
    req = urllib.request.Request(
        s.nim_base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {s.nvidia_api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    last: Exception | None = None
    for attempt in range(len(BACKOFF_S) + 1):
        try:
            with urllib.request.urlopen(req, timeout=s.nim_timeout_s) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            if e.code not in RETRY_STATUS:
                raise NimError(f"NIM HTTP {e.code}: {detail}") from e
            last = NimError(f"NIM HTTP {e.code}: {detail}")
        except (TimeoutError, urllib.error.URLError) as e:
            last = e
        if attempt < len(BACKOFF_S):
            time.sleep(BACKOFF_S[attempt])
    raise NimError(f"NIM request failed after retries: {last}")


def chat(body: dict[str, Any]) -> dict[str, Any]:
    return (_transport or _http_post)(body)


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
