"""LLM gateway on the NVIDIA NIM provider, with a fake transport (no network)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import BaseModel

from app.core import llm, nim
from app.core.config import get_settings

PAN = "ABCDE1234F"  # planted fake


class Tolerance(BaseModel):
    pct_of_line: float
    cap_inr: int


def _resp(content: str, finish: str = "stop") -> dict[str, Any]:
    return {
        "choices": [{"message": {"content": content}, "finish_reason": finish}],
        "usage": {"prompt_tokens": 900, "completion_tokens": 30},
    }


class FakeTransport:
    def __init__(self, replies: list[str], finish: str = "stop") -> None:
        self.replies = list(replies)
        self.finish = finish
        self.bodies: list[dict[str, Any]] = []

    def __call__(self, body: dict[str, Any]) -> dict[str, Any]:
        self.bodies.append(body)
        return _resp(self.replies.pop(0), self.finish)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "cache_dir", tmp_path / "cache")
    monkeypatch.setattr(s, "log_dir", tmp_path / "logs")
    monkeypatch.setattr(s, "llm_provider", "nim")
    monkeypatch.setattr(s, "model_smart", "vendor/smart-model")
    monkeypatch.setattr(s, "model_fast", "vendor/fast-model")
    yield
    nim.set_transport(None)


def _use(fake: FakeTransport) -> FakeTransport:
    nim.set_transport(fake)
    return fake


def test_structured_json_mode_temperature_zero_and_schema(setup) -> None:
    fake = _use(FakeTransport(['{"pct_of_line": 1, "cap_inr": 500}']))
    out = llm.structured(f"Extract. PAN {PAN}", Tolerance, system="Be exact.", model="fast")
    assert out == Tolerance(pct_of_line=1, cap_inr=500)
    body = fake.bodies[0]
    assert body["model"] == "vendor/fast-model"
    assert body["temperature"] == 0
    assert body["response_format"] == {"type": "json_object"}
    system = body["messages"][0]["content"]
    assert system.startswith("Be exact.") and '"cap_inr"' in system  # schema in the prompt
    assert PAN not in json.dumps(body)  # redacted before sending


def test_reasoning_and_fences_are_stripped(setup) -> None:
    _use(
        FakeTransport(
            ['<think>1% and 500…</think>\n```json\n{"pct_of_line": 1, "cap_inr": 500}\n```']
        )
    )
    assert llm.structured("x", Tolerance, prompt_version="t-strip").cap_inr == 500


def test_invalid_output_gets_one_corrective_retry(setup) -> None:
    fake = _use(FakeTransport(['{"pct_of_line": "one"}', '{"pct_of_line": 1, "cap_inr": 500}']))
    out = llm.structured("x", Tolerance, prompt_version="t-retry")
    assert out.cap_inr == 500
    retry = fake.bodies[1]["messages"]
    assert retry[-2]["role"] == "assistant" and "did not validate" in retry[-1]["content"]


def test_still_invalid_after_retry_raises(setup) -> None:
    _use(FakeTransport(["not json", "still not json"]))
    with pytest.raises(llm.LLMError):
        llm.structured("x", Tolerance, prompt_version="t-fail")


def test_truncated_output_raises(setup) -> None:
    _use(FakeTransport(['{"pct_of_line": 1'], finish="length"))
    with pytest.raises(llm.LLMError, match="max_tokens"):
        llm.structured("x", Tolerance, prompt_version="t-len")


def test_complete_logs_tokens_and_caches(setup) -> None:
    fake = _use(FakeTransport(["The limit is ₹500."]))
    a = llm.complete("limit?", prompt_version="t-c", effort="low")
    b = llm.complete("limit?", prompt_version="t-c", effort="low")
    assert a.text == b.text == "The limit is ₹500."
    assert len(fake.bodies) == 1 and "response_format" not in fake.bodies[0]
    assert "output_config" not in fake.bodies[0]  # effort is Anthropic-only
    lines = (get_settings().log_dir / "llm_calls.jsonl").read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    assert (first["input_tokens"], first["output_tokens"], first["model"]) == (
        900,
        30,
        "vendor/smart-model",
    )
    assert json.loads(lines[1])["cached"] is True


def test_extract_json_helper() -> None:
    assert nim.extract_json('noise {"a": 1} trailing') == {"a": 1}
    with pytest.raises(ValueError):
        nim.extract_json("no json here")
