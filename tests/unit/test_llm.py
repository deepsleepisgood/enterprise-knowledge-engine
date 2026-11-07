"""LLM gateway: structured output, redaction, logging, caching, cost.

The fake client mimics the anthropic SDK's `messages.parse` / `messages.create`
response shape. A live test runs only when ANTHROPIC_API_KEY is set.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from app.core import llm
from app.core.config import get_settings

PAN = "ABCDE1234F"  # planted fake


class Tolerance(BaseModel):
    pct_of_line: float
    cap_inr: int


class FakeMessages:
    def __init__(self, stop_reason: str = "end_turn") -> None:
        self.calls: list[dict[str, Any]] = []
        self.stop_reason = stop_reason

    def _resp(self, **extra: Any) -> SimpleNamespace:
        return SimpleNamespace(
            stop_reason=self.stop_reason,
            stop_details=None,
            usage=SimpleNamespace(input_tokens=1200, output_tokens=40),
            **extra,
        )

    def parse(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        return self._resp(parsed_output=kwargs["output_format"](pct_of_line=1.0, cap_inr=500))

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        return self._resp(content=[SimpleNamespace(type="text", text="The limit is ₹500.")])


@pytest.fixture
def fake(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "cache_dir", tmp_path / "cache")
    monkeypatch.setattr(settings, "log_dir", tmp_path / "logs")
    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    monkeypatch.setattr(settings, "model_fast", "claude-haiku-5-5")
    monkeypatch.setattr(settings, "model_smart", "claude-sonnet-5-5")
    messages = FakeMessages()
    llm.set_client(SimpleNamespace(messages=messages))
    yield messages
    llm.set_client(None)


def _log_lines() -> list[dict[str, Any]]:
    path = get_settings().log_dir / "llm_calls.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_structured_returns_validated_object(fake: FakeMessages) -> None:
    out = llm.structured(f"Extract the tolerance. Supplier PAN {PAN}.", Tolerance, model="fast")
    assert out == Tolerance(pct_of_line=1.0, cap_inr=500)

    sent = fake.calls[0]
    assert sent["model"] == get_settings().model_fast
    assert sent["output_format"] is Tolerance
    assert "temperature" not in sent  # rejected by the 5.5 models
    assert PAN not in sent["messages"][0]["content"]  # redacted before sending


def test_call_is_logged_redacted_with_cost(fake: FakeMessages) -> None:
    llm.structured(f"PAN {PAN} please", Tolerance, model="smart")
    (rec,) = _log_lines()
    assert PAN not in json.dumps(rec)
    assert "[REDACTED_PAN]" in rec["prompt"]
    assert rec["model"] == "claude-sonnet-5-5"
    assert rec["input_tokens"] == 1200 and rec["output_tokens"] == 40
    assert rec["cost_usd"] == pytest.approx(1200 * 2 / 1e6 + 40 * 10 / 1e6)
    assert rec["cached"] is False


def test_second_identical_call_hits_cache(fake: FakeMessages) -> None:
    a = llm.structured("same input", Tolerance, prompt_version="t1")
    b = llm.structured("same input", Tolerance, prompt_version="t1")
    assert a == b
    assert len(fake.calls) == 1
    assert [r["cached"] for r in _log_lines()] == [False, True]


def test_prompt_version_changes_cache_key(fake: FakeMessages) -> None:
    llm.structured("same input", Tolerance, prompt_version="t1")
    llm.structured("same input", Tolerance, prompt_version="t2")
    assert len(fake.calls) == 2


def test_complete_returns_text(fake: FakeMessages) -> None:
    res = llm.complete("What is the limit?", model="fast", effort="low")
    assert res.text == "The limit is ₹500."
    assert fake.calls[0]["output_config"] == {"effort": "low"}
    assert res.cost_usd == pytest.approx(1200 * 0.10 / 1e6 + 40 * 0.50 / 1e6)


def test_refusal_raises(fake: FakeMessages) -> None:
    fake.stop_reason = "refusal"
    with pytest.raises(llm.LLMError):
        llm.complete("anything", prompt_version="refusal-test")


@pytest.mark.live_llm
@pytest.mark.skipif(not get_settings().llm_configured, reason="no LLM API key configured")
def test_live_structured_call(tmp_path, monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "cache_dir", tmp_path / "cache")
    monkeypatch.setattr(settings, "log_dir", tmp_path / "logs")
    llm.set_client(None)
    out = llm.structured(
        f"Supplier PAN {PAN}. Rule: a price excess passes if it is no more than the lower "
        "of 1% of the PO line value and ₹500. Extract the percentage and the rupee cap.",
        Tolerance,
        model="fast",
    )
    assert out.cap_inr == 500 and out.pct_of_line == pytest.approx(1.0)
    assert PAN not in (tmp_path / "logs" / "llm_calls.jsonl").read_text(encoding="utf-8")
