"""LLM gateway on the OpenAI provider, with a fake transport (no network)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from app.core import llm, nim
from app.core.config import get_settings

PAN = "ABCDE1234F"  # planted fake


class Tolerance(BaseModel):
    pct_of_line: float
    cap_inr: int


class FakeTransport:
    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.bodies: list[dict[str, Any]] = []

    def __call__(self, body: dict[str, Any]) -> dict[str, Any]:
        self.bodies.append(body)
        return {
            "choices": [{"message": {"content": self.replies.pop(0)}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 100},
        }


@pytest.fixture
def setup(tmp_path, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "cache_dir", tmp_path / "cache")
    monkeypatch.setattr(s, "log_dir", tmp_path / "logs")
    monkeypatch.setattr(s, "llm_provider", "openai")
    monkeypatch.setattr(s, "openai_api_key", "sk-test")
    monkeypatch.setattr(s, "model_smart", "gpt-5")
    monkeypatch.setattr(s, "model_fast", "gpt-4.1-mini")
    monkeypatch.setattr(s, "model_prices", "")
    yield s
    nim.set_transport(None)


def _use(fake: FakeTransport) -> FakeTransport:
    nim.set_transport(fake)
    return fake


def test_settings_point_at_openai(setup) -> None:
    assert setup.llm_configured
    assert setup.chat_api_key == "sk-test"
    assert setup.chat_base_url == "https://api.openai.com/v1"
    assert not setup.is_isoquant
    assert setup.chat_max_rpm == setup.openai_max_rpm


def test_reasoning_model_gets_no_temperature_and_completion_tokens(setup) -> None:
    fake = _use(FakeTransport(['{"pct_of_line": 1, "cap_inr": 500}']))
    out = llm.structured(f"Extract. PAN {PAN}", Tolerance, max_tokens=20000)
    assert out == Tolerance(pct_of_line=1, cap_inr=500)
    body = fake.bodies[0]
    assert body["model"] == "gpt-5"
    assert "temperature" not in body
    assert "max_tokens" not in body and body["max_completion_tokens"] == 20000
    assert body["response_format"] == {"type": "json_object"}
    assert "chat_template_kwargs" not in body  # NIM-only field
    assert PAN not in json.dumps(body)  # redacted before sending


def test_non_reasoning_model_keeps_temperature_zero(setup) -> None:
    fake = _use(FakeTransport(["ok"]))
    llm.complete("hi", model="fast", thinking=False)
    body = fake.bodies[0]
    assert body["model"] == "gpt-4.1-mini"
    assert body["temperature"] == 0
    assert "reasoning_effort" not in body  # rejected by non-reasoning models


def test_reasoning_model_budget_has_a_floor(setup) -> None:
    fake = _use(FakeTransport(["ok", "ok"]))
    llm.complete("short budget", max_tokens=1024)
    assert fake.bodies[0]["max_completion_tokens"] == setup.openai_reasoning_min_tokens
    llm.complete("short budget", model="fast", max_tokens=1024)
    assert fake.bodies[1]["max_completion_tokens"] == 1024  # non-reasoning: as asked


def test_thinking_off_sets_reasoning_effort_on_reasoning_models(setup) -> None:
    fake = _use(FakeTransport(["ok"]))
    llm.complete("hi", thinking=False)
    assert fake.bodies[0]["reasoning_effort"] == "minimal"


def test_effort_is_not_sent_in_anthropic_shape(setup) -> None:
    fake = _use(FakeTransport(["ok"]))
    llm.complete("hi", effort="high")
    assert "output_config" not in fake.bodies[0]


def test_model_prices_from_env(setup, monkeypatch) -> None:
    monkeypatch.setattr(setup, "model_prices", "gpt-5=1.25/10, bad-entry")
    _use(FakeTransport(["ok"]))
    result = llm.complete("price me")
    assert result.cost_usd == pytest.approx(1000 * 1.25 / 1e6 + 100 * 10 / 1e6)
    assert llm.cost_usd("unknown-model", 10, 10) is None


@pytest.mark.parametrize(
    ("model", "reasoning"),
    [
        ("gpt-5", True),
        ("gpt-5-mini", True),
        ("o3", True),
        ("o4-mini", True),
        ("gpt-4.1", False),
        ("gpt-4o-mini", False),
    ],
)
def test_reasoning_model_detection(model: str, reasoning: bool) -> None:
    assert nim.is_openai_reasoning(model) is reasoning


def test_thinking_off_keeps_the_callers_budget(setup) -> None:
    fake = _use(FakeTransport(["ok"]))
    llm.complete("short", thinking=False, max_tokens=2048)
    assert fake.bodies[0]["max_completion_tokens"] == 2048  # no 16k floor: a stuck call ends sooner


class RefuseMinimal(FakeTransport):
    def __call__(self, body: dict[str, Any]) -> dict[str, Any]:
        if body.get("reasoning_effort") == "minimal":
            self.bodies.append(body)
            raise nim.NimError(
                "NIM HTTP 400: Unsupported value: 'reasoning_effort' does not support 'minimal'"
            )
        return super().__call__(body)


def test_minimal_refused_falls_back_to_low_and_is_remembered(setup, monkeypatch) -> None:
    monkeypatch.setattr(nim, "_NO_MINIMAL", set())
    fake = _use(RefuseMinimal(["ok", "ok"]))
    assert llm.complete("one", thinking=False).text == "ok"
    assert [b.get("reasoning_effort") for b in fake.bodies] == ["minimal", "low"]
    llm.complete("two", thinking=False)
    assert fake.bodies[-1]["reasoning_effort"] == "low"  # no second refused call


def test_other_errors_are_not_swallowed(setup) -> None:
    class Broken(FakeTransport):
        def __call__(self, body: dict[str, Any]) -> dict[str, Any]:
            raise nim.NimError("NIM HTTP 401: invalid key")

    _use(Broken([]))
    with pytest.raises(Exception, match="401"):
        llm.complete("x", thinking=False)


def test_openai_timeout_is_shorter(setup) -> None:
    assert setup.chat_timeout_s == setup.openai_timeout_s == 120


def test_empty_path_settings_mean_default(monkeypatch) -> None:
    from app.core.config import ROOT, Settings

    monkeypatch.setenv("BLOB_DIR", "")
    monkeypatch.setenv("CACHE_DIR", "  ")
    s = Settings()
    assert s.blob_dir == ROOT / "data" / "blobs"
    assert s.cache_dir == ROOT / ".cache" / "llm"
    monkeypatch.setenv("BLOB_DIR", "/data/blobs")
    assert Settings().blob_dir == Path("/data/blobs")  # a Path: "\data\blobs" on Windows


def test_judge_model_setting(setup, monkeypatch) -> None:
    from evaluation import judge

    seen: dict[str, Any] = {}

    def fake_structured(prompt: str, schema: Any, **kw: Any) -> Any:
        seen.update(kw)
        return schema(verdict="correct", reason="ok")

    card = {"status": "answered", "rule": {"text": "x"}}
    monkeypatch.setattr(setup, "judge_model", "gpt-5")
    judge.judge("q", "gold", "factual", card, fake_structured)
    assert seen["model"] == "gpt-5"
    monkeypatch.setattr(setup, "judge_model", "")
    judge.judge("q", "gold", "factual", card, fake_structured)
    assert seen["model"] == "smart"
