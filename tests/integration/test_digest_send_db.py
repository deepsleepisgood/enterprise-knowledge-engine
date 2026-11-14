"""Sending the digest (Phase 11): the API when nothing is set up, a send to email and Teams with
fake transports, and the daily schedule queueing one send per local day."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.core import config
from app.core.db import session_scope
from app.distribute import channels, delivery
from app.store import jobs, kb
from app.store.models import Job

pytestmark = pytest.mark.db

HOOK = "https://example.invalid/workflows/run?sig=SECRET"


@pytest.fixture
def configured(db, monkeypatch):
    for k, v in {
        "SMTP_HOST": "smtp.example.invalid",
        "SMTP_USER": "bot@example.invalid",
        "SMTP_PASSWORD": "pw-SECRET",
        "DIGEST_EMAIL_TO": "team@example.invalid",
        "TEAMS_WEBHOOK_URL": HOOK,
        "DIGEST_SEND_AT": "18:00",
        "DIGEST_UTC_OFFSET_MINUTES": "330",
    }.items():
        monkeypatch.setenv(k, v)
    config.get_settings.cache_clear()
    sent: dict[str, list] = {"email": [], "teams": []}

    class FakeSMTP:
        def __init__(self, s):
            pass

        def login(self, u, p):
            pass

        def send_message(self, msg):
            sent["email"].append(msg)

        def quit(self):
            pass

    def post(url: str, data: bytes) -> int:
        sent["teams"].append(json.loads(data))
        return 202

    monkeypatch.setattr(channels, "_smtp", FakeSMTP)
    monkeypatch.setattr(channels, "_post", post)
    with session_scope() as s:
        v = kb.bump_kb_version(s, "test")
        kb.record_change(s, v, "extraction of abc: 2 new, 0 revised, 0 retired facts")
    yield sent
    monkeypatch.undo()
    config.get_settings.cache_clear()


def test_send_without_a_channel_is_refused(db) -> None:
    with TestClient(create_app()) as client:
        st = client.get("/digest/channels").json()
        assert st["email"]["configured"] is False and st["schedule"] is None
        r = client.post("/digest/send", json={})
        assert r.status_code == 409


def test_send_now_reaches_both_channels(configured) -> None:
    with TestClient(create_app()) as client:
        st = client.get("/digest/channels").json()
        assert st["email"] == {"configured": True, "recipients": 1}
        assert st["schedule"]["send_at"] == "18:00"
        assert "SECRET" not in json.dumps(st)
        assert client.post("/digest/send", json={"channels": ["fax"]}).status_code == 422
        r = client.post("/digest/send", json={"utc_offset_minutes": 0})
        assert r.status_code == 200
        res = {x["channel"]: x for x in r.json()["results"]}
    assert res["email"]["ok"] and res["teams"]["ok"]
    assert len(configured["email"]) == 1 and len(configured["teams"]) == 1
    assert "1 other knowledge updates" in configured["email"][0].get_body(("plain",)).get_content()


def test_the_daily_send_is_queued_once_per_local_day(configured) -> None:
    before = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)  # 17:30 in UTC+05:30
    after = datetime(2026, 11, 14, 12, 45, tzinfo=UTC)
    with session_scope() as s:
        assert delivery.schedule_tick(s, before) is None
        job = delivery.schedule_tick(s, after)
        assert job is not None
        assert delivery.schedule_tick(s, after) is None  # already queued for that day
        assert delivery.schedule_tick(s, datetime(2026, 11, 15, 13, 0, tzinfo=UTC)) is not None
        row = s.get(Job, job)
        assert row.payload == {"day": "2026-11-14", "utc_offset_minutes": 330}
        assert row.max_attempts == 1
        assert jobs.exists_with(s, delivery.KIND, "day", "2026-11-14")


def test_the_job_skips_an_empty_day_and_sends_a_busy_one(configured) -> None:
    out = delivery.run({"day": "2020-01-01", "utc_offset_minutes": 0})
    assert out["skipped"] and not configured["email"]
    today = datetime.now(UTC).date().isoformat()
    out = delivery.run({"day": today, "utc_offset_minutes": 0})
    assert [r["ok"] for r in out["results"]] == [True, True]
