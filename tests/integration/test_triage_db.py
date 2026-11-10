"""Triage of incoming messages (BUILD_PLAN Phase 9, TEST_PLAN level 9), with a fake triage
model and the fake extractor of test_graph_db (no network)."""

from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.core.db import session_scope
from app.graph import pipeline as gp
from app.graph.compare import deterministic
from app.ingest import pipeline as ip
from app.ingest.connectors import from_eml
from app.ingest.intake import submit
from app.ingest.triage import TriageOut
from app.store import episodes as estore
from app.store import kb
from app.worker import drain
from tests.integration.test_graph_db import V1, fake_structured, graph  # noqa: F401

pytestmark = pytest.mark.db


def _eml(subject: str, body: str, sender: str = "Asha, HR <asha@example.com>") -> bytes:
    lines = [
        f"From: {sender}",
        "To: HR team <hr@example.com>",
        f"Subject: {subject}",
        "Date: Mon, 4 May 2026 10:00:00 +0000",
        "Content-Type: text/plain; charset=utf-8",
        "",
        body,
    ]
    return "\r\n".join(lines).encode()


def fake_triage(prompt: str, schema, **kw) -> TriageOut:
    text = prompt.lower()
    if "out of the office" in text:
        return TriageOut(reason="auto-reply", label="noise")
    if "how many days" in text:
        return TriageOut(reason="asks", label="question", question="How many leave days?")
    if "most people take" in text:
        return TriageOut(reason="habit", label="tacit_tip")
    return TriageOut(reason="rule", label="rule_change")


@pytest.fixture
def mail(graph, monkeypatch):  # noqa: F811
    ingest, build = graph
    build(ingest(V1, "v1.md"))  # the owner's seeding
    monkeypatch.setattr(ip, "_triage_structured", lambda: fake_triage)
    monkeypatch.setattr(get_settings(), "governance", True)
    asked: list[str] = []

    def fake_ask(question, **kw):
        asked.append(question)
        return {"status": "answered", "rule": {"text": "20 days."}, "kb_version": 1}

    monkeypatch.setattr("app.answer.pipeline.ask", fake_ask)

    def send(raw: bytes) -> tuple[str, bool]:
        with session_scope() as s:
            eid, created = submit(s, from_eml(raw, channel="email")[0])
        drain(kinds=["parse_episode"])
        return eid, created

    return send, asked


def test_noise_is_kept_but_nothing_is_extracted(mail) -> None:
    send, _ = mail
    eid, _ = send(_eml("Out of office", "I am out of the office until Monday."))
    with session_scope() as s:
        ep = estore.get_episode(s, eid)
        assert (ep.status, ep.triage_label) == ("ignored", "noise")
        assert estore.list_sources(s, eid) == []  # the original is kept, nothing else


def test_an_emailed_question_is_answered_and_changes_nothing(mail) -> None:
    send, asked = mail
    with session_scope() as s:
        before = kb.current_kb_version(s)
    eid, _ = send(_eml("Leave", "Hi, how many days of annual leave do I get?"))
    with session_scope() as s:
        ep = estore.get_episode(s, eid)
        assert (ep.status, ep.triage_label) == ("answered", "question")
        assert ep.meta["answer"]["text"] == "20 days."
        assert estore.list_sources(s, eid) == [] and kb.current_kb_version(s) == before
    assert asked == ["How many leave days?"]


def test_a_tip_is_practice_and_waits_for_the_owner(mail) -> None:
    send, _ = mail
    eid, _ = send(_eml("Tip", "Most people take 22 days, they save the rest for the cash-out."))
    out = gp.extract_and_publish(
        eid, structured_fn=fake_structured, compare=deterministic, embed_fn=None, govern=True
    )
    assert out["governance"] == "pending"
    with session_scope() as s:
        [src] = estore.list_sources(s, eid)
        assert (src.meta or {}).get("practice") is True
        item = kb.get_review_item(s, out["review_item"])
        assert any("tip" in r for r in item.payload["reasons"])


def test_a_forwarded_message_is_a_confirmation_not_a_new_episode(mail) -> None:
    send, _ = mail
    body = "From 1 June staff get 25 days of annual leave a year."
    first, created = send(_eml("Leave update", body))
    fwd = (
        "FYI\r\n\r\n---------- Forwarded message ---------\r\n"
        "From: Asha, HR <asha@example.com>\r\nSubject: Leave update\r\n\r\n" + body
    )
    again, created_again = send(_eml("Fwd: Leave update", fwd, "Ravi <ravi@example.com>"))
    assert created and not created_again and again == first
    with session_scope() as s:
        assert estore.get_episode(s, first).confirmations == 1
