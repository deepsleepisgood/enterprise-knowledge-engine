"""The only way the engine talks to an LLM.

Every call is redacted, cached on disk, logged (redacted) to logs/llm_calls.jsonl,
and costed. Two call styles:

    complete(prompt, ...)            -> LLMResult (free text)
    structured(prompt, Schema, ...)  -> Schema instance (validated Pydantic object)

Providers (LLM_PROVIDER):
- anthropic: the anthropic SDK; structured output via `messages.parse`. The 5.5 models
  reject `temperature`, so none is sent; reproducibility comes from the disk cache.
- nim: NVIDIA NIM (OpenAI-compatible), app/core/nim.py. Temperature 0, JSON mode, the
  JSON Schema in the system prompt, Pydantic validation and one corrective retry.
The cache key includes the model id, so switching provider never reuses another's output.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from app.core.config import get_settings
from app.core.redaction import redact

T = TypeVar("T", bound=BaseModel)

MAX_TOKENS_CEILING = 32768  # NIM: a truncated reply is retried with double budget up to this

# USD per million tokens (input, output). Source: Anthropic pricing, Oct 2026.
PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}


class LLMError(RuntimeError):
    pass


class LLMResult(BaseModel):
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float | None
    latency_ms: int
    cached: bool


# --- client injection (tests swap in a fake) -------------------------------------------

_client: Any = None


def set_client(client: Any) -> None:
    """Use this client object instead of anthropic.Anthropic() (for tests)."""
    global _client
    _client = client


def _get_client() -> Any:
    global _client
    if _client is None:
        import anthropic

        settings = get_settings()
        _client = anthropic.Anthropic(api_key=settings.anthropic_api_key or None)
    return _client


# --- helpers ---------------------------------------------------------------------------


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float | None:
    price = PRICES_PER_MTOK.get(model)
    if price is None:
        return None
    return round(input_tokens * price[0] / 1e6 + output_tokens * price[1] / 1e6, 6)


def cache_key(**parts: Any) -> str:
    blob = json.dumps(parts, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _cache_path(key: str) -> Path:
    d = get_settings().cache_dir / key[:2]
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{key}.json"


_log_lock = threading.Lock()


def _log(record: dict[str, Any]) -> None:
    """Append one JSON line. Locked: extraction runs in parallel threads."""
    log_dir = get_settings().log_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False) + "\n"
    with _log_lock, (log_dir / "llm_calls.jsonl").open("a", encoding="utf-8") as f:
        f.write(line)


def _resolve_model(model: str | None) -> str:
    s = get_settings()
    aliases = {
        None: s.model_smart,
        "fast": s.model_fast,
        "smart": s.model_smart,
        "vision": s.model_vision or s.model_smart,
    }
    return aliases.get(model, model)  # type: ignore[arg-type]


def _usage(resp: Any) -> tuple[int, int]:
    usage = getattr(resp, "usage", None)
    return (
        int(getattr(usage, "input_tokens", 0) or 0),
        int(getattr(usage, "output_tokens", 0) or 0),
    )


def _check_stop(resp: Any) -> None:
    reason = getattr(resp, "stop_reason", None)
    if reason == "refusal":
        raise LLMError(f"model refused: {getattr(resp, 'stop_details', None)}")
    if reason == "max_tokens":
        raise LLMError("response hit max_tokens; raise max_tokens for this call")


def _call(
    *,
    style: str,
    prompt: str,
    system: str | None,
    model: str | None,
    prompt_version: str,
    max_tokens: int,
    effort: str | None,
    schema: type[BaseModel] | None,
    invoke: Callable[[dict[str, Any]], tuple[Any, Any]],
    key_extra: str | None = None,
    thinking: bool | None = None,
) -> tuple[Any, LLMResult]:
    """Shared redact -> cache -> call -> log path. `invoke` returns (payload, raw_response)."""
    model_id = _resolve_model(model)
    safe_prompt = redact(prompt)
    safe_system = redact(system) if system else None
    schema_sig = schema.model_json_schema() if schema else None
    key = cache_key(
        v=prompt_version,
        model=model_id,
        style=style,
        system=safe_system,
        prompt=safe_prompt,
        schema=schema_sig,
        effort=effort,
        **({"extra": key_extra} if key_extra else {}),
        **({"thinking": False} if thinking is False else {}),
    )
    path = _cache_path(key)
    base_log = {
        "at": datetime.now(UTC).isoformat(),
        "style": style,
        "model": model_id,
        "prompt_version": prompt_version,
        "cache_key": key,
        "system": safe_system,
        "prompt": safe_prompt,
    }

    if path.exists():
        hit = json.loads(path.read_text(encoding="utf-8"))
        result = LLMResult(**{**hit["result"], "cached": True, "latency_ms": 0, "cost_usd": 0.0})
        _log(
            {
                **base_log,
                "cached": True,
                "input_tokens": 0,
                "output_tokens": 0,
                "cost_usd": 0.0,
                "latency_ms": 0,
            }
        )
        return hit["payload"], result

    request: dict[str, Any] = {
        "model": model_id,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": safe_prompt}],
    }
    if safe_system:
        request["system"] = safe_system
    if effort and _provider() != "nim":
        request["output_config"] = {"effort": effort}
    if thinking is False and _provider() == "nim":
        request["thinking_off"] = True  # read by the NIM adapters, never sent to Anthropic

    started = time.perf_counter()
    try:
        payload, resp = invoke(request)
    except LLMError:
        raise
    except Exception as exc:  # SDK errors are re-raised with context, after logging
        _log({**base_log, "cached": False, "error": f"{type(exc).__name__}: {exc}"})
        raise
    latency_ms = int((time.perf_counter() - started) * 1000)
    in_tok, out_tok = _usage(resp)
    result = LLMResult(
        text=payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False),
        model=model_id,
        input_tokens=in_tok,
        output_tokens=out_tok,
        cost_usd=cost_usd(model_id, in_tok, out_tok),
        latency_ms=latency_ms,
        cached=False,
    )
    path.write_text(
        json.dumps({"payload": payload, "result": result.model_dump()}, ensure_ascii=False),
        encoding="utf-8",
    )
    _log(
        {
            **base_log,
            "cached": False,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "cost_usd": result.cost_usd,
            "latency_ms": latency_ms,
            "output": redact(result.text),
        }
    )
    return payload, result


# --- NVIDIA NIM -----------------------------------------------------------------------


class _NimResp:
    """Adapts a NIM response to the usage shape `_call` reads."""

    def __init__(self, input_tokens: int, output_tokens: int) -> None:
        self.usage = type("U", (), {"input_tokens": input_tokens, "output_tokens": output_tokens})


def _nim_complete(req: dict[str, Any]) -> tuple[Any, Any]:
    from app.core import nim

    body = nim.build_body(
        model=req["model"],
        system=req.get("system"),
        messages=req["messages"],
        max_tokens=req["max_tokens"],
        json_mode=False,
    )
    if req.get("thinking_off"):
        body["chat_template_kwargs"] = {"enable_thinking": False}
    resp = nim.chat(body)
    text, finish = nim.message_text(resp)
    if finish == "length":
        raise LLMError("response hit max_tokens; raise max_tokens for this call")
    return text, _NimResp(*nim.usage(resp))


def _nim_structured(req: dict[str, Any], schema: type[BaseModel]) -> tuple[Any, Any]:
    from pydantic import ValidationError

    from app.core import nim

    parts = (req.get("system"), nim.schema_instruction(schema.model_json_schema()))
    system = "\n\n".join(p for p in parts if p)
    messages = list(req["messages"])
    in_tok = out_tok = 0
    budget = req["max_tokens"]
    attempt = 0
    while True:
        body = nim.build_body(
            model=req["model"],
            system=system,
            messages=messages,
            max_tokens=budget,
            json_mode=True,
        )
        if req.get("thinking_off"):
            body["chat_template_kwargs"] = {"enable_thinking": False}
        resp = nim.chat(body)
        i, o = nim.usage(resp)
        in_tok, out_tok = in_tok + i, out_tok + o
        text, finish = nim.message_text(resp)
        if finish == "length":
            # Reasoning models spend output tokens on thinking; one retry with double budget.
            if budget >= MAX_TOKENS_CEILING:
                raise LLMError("response hit max_tokens; raise max_tokens for this call")
            budget = min(budget * 2, MAX_TOKENS_CEILING)
            continue
        try:
            obj = schema.model_validate(nim.extract_json(text))
            return obj.model_dump(mode="json"), _NimResp(in_tok, out_tok)
        except (ValueError, ValidationError) as exc:
            attempt += 1
            if attempt == 2:
                raise LLMError(f"model output did not match {schema.__name__}: {exc}") from exc
            messages += [
                {"role": "assistant", "content": text},
                {
                    "role": "user",
                    "content": f"That did not validate: {str(exc)[:800]}\n"
                    "Return only the corrected JSON object.",
                },
            ]


def _provider() -> str:
    return get_settings().llm_provider.strip().lower()


# --- public API ------------------------------------------------------------------------


def complete(
    prompt: str,
    *,
    system: str | None = None,
    model: str | None = None,
    prompt_version: str = "v1",
    max_tokens: int = 4096,
    effort: str | None = None,
    thinking: bool | None = None,
) -> LLMResult:
    """Free-text completion. `model` is "fast", "smart" (default) or a model id.

    `thinking=False` asks a reasoning model to answer directly (NIM chat-template switch);
    None leaves the provider's default."""

    def invoke(req: dict[str, Any]) -> tuple[Any, Any]:
        if _provider() == "nim":
            return _nim_complete(req)
        resp = _get_client().messages.create(**req)
        _check_stop(resp)
        text = "".join(getattr(b, "text", "") for b in resp.content if b.type == "text")
        return text, resp

    _, result = _call(
        style="complete",
        prompt=prompt,
        system=system,
        model=model,
        prompt_version=prompt_version,
        max_tokens=max_tokens,
        effort=effort,
        schema=None,
        invoke=invoke,
        thinking=thinking,
    )
    return result


def structured(
    prompt: str,
    schema: type[T],
    *,
    system: str | None = None,
    model: str | None = None,
    prompt_version: str = "v1",
    max_tokens: int = 8192,
    effort: str | None = None,
    thinking: bool | None = None,
) -> T:
    """Return a validated `schema` instance using the API's structured outputs."""

    def invoke(req: dict[str, Any]) -> tuple[Any, Any]:
        if _provider() == "nim":
            return _nim_structured(req, schema)
        resp = _get_client().messages.parse(**req, output_format=schema)
        _check_stop(resp)
        parsed = resp.parsed_output
        if parsed is None:
            raise LLMError("structured call returned no parsed output")
        return schema.model_validate(parsed).model_dump(mode="json"), resp

    payload, _ = _call(
        style="structured",
        prompt=prompt,
        system=system,
        model=model,
        prompt_version=prompt_version,
        max_tokens=max_tokens,
        effort=effort,
        schema=schema,
        invoke=invoke,
        thinking=thinking,
    )
    return schema.model_validate(payload)


def vision(
    prompt: str,
    images: list[tuple[bytes, str]],
    *,
    system: str | None = None,
    model: str | None = "vision",
    prompt_version: str = "v1",
    max_tokens: int = 8192,
) -> LLMResult:
    """Read page images (bytes, media type) and return text, e.g. structured markdown.

    Text parts are redacted as usual; images cannot be, so the returned text is redacted in the
    log and by the caller before storage. Cache key includes a hash of every image.
    """
    import base64

    digest = hashlib.sha256(b"".join(hashlib.sha256(b).digest() for b, _ in images)).hexdigest()

    def invoke(req: dict[str, Any]) -> tuple[Any, Any]:
        text = req["messages"][0]["content"]
        if _provider() == "nim":
            from app.core import nim

            parts: list[dict[str, Any]] = [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mt};base64,{base64.b64encode(b).decode()}"},
                }
                for b, mt in images
            ]
            parts.append({"type": "text", "text": text})
            body = nim.build_body(
                model=req["model"],
                system=req.get("system"),
                messages=[{"role": "user", "content": parts}],  # type: ignore[list-item]
                max_tokens=req["max_tokens"],
                json_mode=False,
            )
            resp = nim.chat(body)
            out, finish = nim.message_text(resp)
            if finish == "length":
                raise LLMError("response hit max_tokens; raise max_tokens for this call")
            return out, _NimResp(*nim.usage(resp))
        blocks: list[dict[str, Any]] = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": mt,
                    "data": base64.b64encode(b).decode(),
                },
            }
            for b, mt in images
        ]
        blocks.append({"type": "text", "text": text})
        resp = _get_client().messages.create(
            **{**req, "messages": [{"role": "user", "content": blocks}]}
        )
        _check_stop(resp)
        return "".join(getattr(b, "text", "") for b in resp.content if b.type == "text"), resp

    _, result = _call(
        style="vision",
        prompt=prompt,
        system=system,
        model=model,
        prompt_version=prompt_version,
        max_tokens=max_tokens,
        effort=None,
        schema=None,
        invoke=invoke,
        key_extra=digest,
    )
    return result
