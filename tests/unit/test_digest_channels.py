"""Digest delivery channels: what counts as set up, the message bodies, and the transports
(fakes here: nothing leaves the machine)."""

from __future__ import annotations

import json
import smtplib
from datetime import UTC, date, datetime

from app.core.config import Settings
from app.distribute import channels
from app.distribute.delivery import due_day

HOOK = "https://example.invalid/workflows/abc/triggers/manual/run?sig=SECRET"


def _settings(**kw) -> Settings:
    base = {
        "smtp_host": "",
        "digest_email_to": "",
        "teams_webhook_url": "",
        "digest_send_at": "",
        "smtp_user": "",
        "smtp_password": "",
        "smtp_from": "",
        "web_base_url": "",
    }
    return Settings(_env_file=None, **{**base, **kw})


def _change(i: int, old: str = "1%", new: str = "2%", status: str = "confirmed") -> dict:
    return {
        "id": i,
        "topic": f"Topic <{i}>",
        "summary": f"change {i}",
        "attribute": "x.pct",
        "old_value": old,
        "new_value": new,
        "effective_at": "2026-11-16T00:00:00+00:00",
        "source_label": "Memo & note",
        "status": status,
    }


def _digest(n: int = 2, empty: bool = False) -> dict:
    rules = [] if empty else [_change(i) for i in range(n)]
    return {
        "day": "2026-11-14",
        "rules": rules,
        "withdrawn": [],
        "updates": 3,
        "document_edits": [0] if rules else [],
        "waiting_review": 1,
        "to_acknowledge": [],
        "users": 4,
        "empty": empty,
        "text": "Changes on 14 Nov 2026\n- plain text",
    }


class FakeSMTP:
    sent: list = []

    def __init__(self, s: Settings) -> None:
        self.logged_in = None

    def login(self, user: str, pw: str) -> None:
        self.logged_in = user

    def send_message(self, msg) -> None:
        FakeSMTP.sent.append(msg)

    def quit(self) -> None:
        pass


def test_nothing_is_set_up_by_default() -> None:
    st = channels.status(_settings())
    assert st == {
        "email": {"configured": False, "recipients": 0},
        "teams": {"configured": False},
        "schedule": None,
    }
    assert channels.deliver(_digest(), s=_settings()) == []


def test_status_reports_counts_and_schedule_but_no_secrets() -> None:
    s = _settings(
        smtp_host="smtp.example.invalid",
        smtp_user="bot@example.invalid",
        smtp_password="pw-SECRET",
        digest_email_to="a@example.invalid, b@example.invalid",
        teams_webhook_url=HOOK,
        digest_send_at="18:00",
        digest_utc_offset_minutes=330,
    )
    st = channels.status(s)
    assert st["email"] == {"configured": True, "recipients": 2}
    assert st["teams"] == {"configured": True}
    assert st["schedule"]["send_at"] == "18:00"
    dumped = json.dumps(st)
    assert "SECRET" not in dumped and "example.invalid" not in dumped


def test_email_needs_a_server_recipients_and_a_sender() -> None:
    assert not channels.email_configured(_settings(smtp_host="h", digest_email_to="a@x"))
    assert channels.email_configured(
        _settings(smtp_host="h", digest_email_to="a@x", smtp_from="f@x")
    )
    assert not channels.teams_configured(_settings(teams_webhook_url="http://insecure"))


def test_email_has_text_and_escaped_html_parts() -> None:
    FakeSMTP.sent = []
    s = _settings(
        smtp_host="h",
        smtp_user="bot@x",
        smtp_password="pw",
        digest_email_to="a@x,b@x",
        web_base_url="https://app.example.invalid/",
    )
    [r] = channels.deliver(_digest(), ["email"], s, smtp_factory=FakeSMTP)
    assert r == {"channel": "email", "ok": True, "detail": "sent to 2 recipients"}
    msg = FakeSMTP.sent[0]
    assert msg["Subject"] == "Knowledge base digest, 14 Nov 2026: 2 rule changes"
    assert msg["To"] == "a@x, b@x"
    text = msg.get_body(("plain",)).get_content()
    page = msg.get_body(("html",)).get_content()
    assert "https://app.example.invalid/changes" in text
    assert "Topic &lt;0&gt;" in page and "Memo &amp; note" in page and "1% → 2%" in page
    assert "<Topic" not in page


def test_teams_card_is_an_adaptive_card_and_caps_the_list() -> None:
    posted = []

    def post(url: str, data: bytes) -> int:
        posted.append((url, json.loads(data)))
        return 202

    s = _settings(teams_webhook_url=HOOK, web_base_url="https://app.example.invalid")
    [r] = channels.deliver(_digest(n=channels.MAX_ITEMS + 3), ["teams"], s, post=post)
    assert r["ok"] and posted[0][0] == HOOK
    msg = posted[0][1]
    att = msg["attachments"][0]
    assert msg["type"] == "message"
    assert att["contentType"] == "application/vnd.microsoft.card.adaptive"
    card = att["content"]
    assert card["type"] == "AdaptiveCard"
    containers = [b for b in card["body"] if b["type"] == "Container"]
    assert len(containers) == channels.MAX_ITEMS
    assert any("and 3 more" in b.get("text", "") for b in card["body"])
    assert card["actions"][0]["url"] == "https://app.example.invalid/changes"


def test_a_failing_channel_is_reported_redacted_and_does_not_stop_the_other() -> None:
    def post(url: str, data: bytes) -> int:
        raise OSError(f"cannot reach {url}")

    class BadSMTP(FakeSMTP):
        def login(self, user: str, pw: str) -> None:
            raise smtplib.SMTPAuthenticationError(535, f"bad password {pw}".encode())

    s = _settings(
        smtp_host="h",
        smtp_user="u@x",
        smtp_password="pw-SECRET",
        digest_email_to="a@x",
        teams_webhook_url=HOOK,
    )
    res = channels.deliver(_digest(), None, s, smtp_factory=BadSMTP, post=post)
    assert [r["channel"] for r in res] == ["email", "teams"]
    assert not any(r["ok"] for r in res)
    assert all("SECRET" not in r["detail"] for r in res)
    assert "[hidden]" in res[1]["detail"]


def test_a_channel_not_set_up_says_so() -> None:
    assert channels.deliver(_digest(), ["teams"], _settings()) == [
        {"channel": "teams", "ok": False, "detail": "not set up"}
    ]


def test_empty_digest_message() -> None:
    d = _digest(empty=True)
    assert channels.subject(d).endswith("no rule changes")
    assert "No changes" in channels.digest_html(d)


def test_send_time_uses_the_team_time_zone() -> None:
    # 18:00 in UTC+05:30 is 12:30 UTC
    assert due_day(datetime(2026, 11, 14, 12, 29, tzinfo=UTC), "18:00", 330) is None
    assert due_day(datetime(2026, 11, 14, 12, 30, tzinfo=UTC), "18:00", 330) == date(2026, 11, 14)
    # 23:00 UTC is already the next local day
    assert due_day(datetime(2026, 11, 14, 23, 0, tzinfo=UTC), "02:00", 330) == date(2026, 11, 15)
    assert due_day(datetime(2026, 11, 14, 23, 0, tzinfo=UTC), "25:00", 0) is None
    assert channels.parse_send_at("") is None
