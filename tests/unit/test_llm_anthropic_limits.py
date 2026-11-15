"""Anthropic calls are capped per process and retried more than the SDK default."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from app.core import llm
from app.core.config import Settings, get_settings


@pytest.fixture
def fresh(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setattr(llm, "_anthropic_slots", None)
    saved = llm._client
    yield monkeypatch
    llm.set_client(saved)
    get_settings.cache_clear()


def test_defaults_retry_more_than_the_sdk() -> None:
    s = Settings(_env_file=None)
    assert s.anthropic_max_retries > 2
    assert s.anthropic_max_concurrent >= 1


def test_calls_never_exceed_the_cap(fresh) -> None:
    fresh.setenv("ANTHROPIC_MAX_CONCURRENT", "3")
    state = {"now": 0, "peak": 0}
    lock = threading.Lock()

    class Messages:
        def create(self, **_: Any) -> str:
            with lock:
                state["now"] += 1
                state["peak"] = max(state["peak"], state["now"])
            time.sleep(0.05)
            with lock:
                state["now"] -= 1
            return "ok"

    class Client:
        messages = Messages()

    llm.set_client(Client())
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(lambda _: llm._anthropic_call("create", model="m"), range(12)))
    assert results == ["ok"] * 12
    assert state["peak"] == 3


def test_client_gets_retry_and_timeout_settings(fresh) -> None:
    anthropic = pytest.importorskip("anthropic")
    fresh.setenv("ANTHROPIC_API_KEY", "test-key")
    fresh.setenv("ANTHROPIC_MAX_RETRIES", "7")
    fresh.setenv("ANTHROPIC_TIMEOUT_S", "45")
    llm.set_client(None)
    client = llm._get_client()
    assert isinstance(client, anthropic.Anthropic)
    assert client.max_retries == 7
    assert client.timeout == 45
