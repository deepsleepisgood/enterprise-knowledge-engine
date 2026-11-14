"""Expert capture (T10) and the Teams chat-export connector, against the database.

Uses the leave-policy corpus and fake extractor of test_graph_db; every model call is faked.

Capture: an entry is held for its reviewer whatever GOVERNANCE says, publishes one practice note
about its subject once approved, is used like a data-row note when a question names the subject,
and a reviewer's edit replaces it. Teams: an export becomes one episode per thread; questions are
recorded but never answered again, noise is dropped, and a tip is extracted and held.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.capture import interview as cap
from app.core.config import get_settings
from app.core.db import session_scope
from app.govern import apply as gapply
from app.graph import pipeline as gp
from app.graph.rows import CAPTURE_ORIGIN
from app.ingest import pipeline as ip
from app.ingest.connectors import from_upload
from app.ingest.intake import submit as intake_submit
from app.ingest.triage import TriageOut
from app.store import episodes as estore
from app.store import facts as fstore
from app.store import kb
from app.worker import drain
from tests.integration.test_graph_db import V1, graph  # noqa: F401

pytestmark = pytest.mark.db

ENTRY = cap.Entry(
    subject="Contoso Couriers",
    habit="Re-sends a late-paid invoice with /A added to the number",
    trigger="same amount and date as an invoice already posted",
    what_to_do="check for the original before posting",
    evidence="three cases this year",
    author="Asha Rao",
    author_role="Senior Processor",
    date=dt.date(2026, 5, 4),
)


@pytest.fixture
def seeded(graph, monkeypatch):  # noqa: F811
    ingest, build = graph
    build(ingest(V1, "v1.md"))  # the owner's seeding
    monkeypatch.setattr(gp, "_default_structured", lambda: None)  # deterministic resolution
    return ingest, build


def _captured(entry: cap.Entry = ENTRY, reviewer: str = "Team Lead", **kw) -> str:
    with session_scope() as s:
        eid = cap.submit(s, entry, reviewer, **kw)
    drain(kinds=["parse_episode", "capture_entry"])
    return eid


def _open_item(s, episode_id: str):  # noqa: ANN001, ANN202
    return next(
        i
        for i in kb.list_review_items(s)
        if i.kind == "change" and i.payload.get("episode_id") == episode_id
    )


def test_an_entry_waits_for_its_reviewer_even_without_governance(seeded) -> None:
    assert not get_settings().governance  # tests seed without governance: capture still waits
    with session_scope() as s:
        before = kb.current_kb_version(s)
    check = cap.RuleCheck(verdict="compatible", reason="fits the duplicate rule")
    eid = _captured(check=check)
    with session_scope() as s:
        ep = estore.get_episode(s, eid)
        assert ep.status == "pending_review" and ep.channel == cap.CHANNEL
        (src,) = estore.list_sources(s, eid)
        assert src.doc_type == "interview" and src.meta.get("practice") is True
        (fact,) = fstore.live_for_episode(s, eid, statuses=["pending"])
        assert fact.kind == "practice" and fact.origin_key.startswith(CAPTURE_ORIGIN)
        assert fact.statement.startswith("Contoso Couriers: Re-sends a late-paid invoice")
        assert fact.attribute.endswith("supplier_habits.habit_note")
        item = _open_item(s, eid)
        assert item.payload["capture"]["reviewer"] == "Team Lead"
        assert item.payload["capture"]["check"]["verdict"] == "compatible"
        assert any("held for Team Lead" in r for r in item.payload["reasons"])
        assert kb.current_kb_version(s) == before  # nothing published yet
        (listed,) = cap.entries(s)
        assert listed["review"]["id"] == item.id and listed["fact_status"] == "pending"


def test_an_approved_entry_is_a_note_about_its_subject(seeded) -> None:
    eid = _captured()
    with session_scope() as s:
        item = _open_item(s, eid)
        assert kb.decide_review_item(s, item.id, "approved", "owner-1", item.row_version)
    gapply.apply_decision(item.id)
    with session_scope() as s:
        (fact,) = fstore.live_for_episode(s, eid, statuses=["current"])
        assert fact.meta.get("approved_by") == "owner-1"
        assert estore.get_episode(s, eid).status == "published"
        # The plug-in's vendor panel and the answer path find it by its subject's names.
        (note,) = fstore.notes_about(s, ["contoso couriers"], CAPTURE_ORIGIN)
        assert note.id == fact.id
        known = cap.known_notes(s)
        assert known["by_origin"].get("capture") == 1
    from app.answer.retrieve import retrieve

    same = [1.0] + [0.0] * 383
    with session_scope() as s:
        got = retrieve(
            s,
            "Contoso Couriers sent an invoice ending in /A, what do I do?",
            None,
            None,
            None,
            dt.date(2026, 6, 1),
            lambda texts: [same for _ in texts],  # every text alike: isolates the origin rule
            lambda q, docs: [0.0 for _ in docs],
        )
    assert fact.id in [f.id for f in got.named_practice]


def test_a_reviewers_edit_replaces_the_entry(seeded) -> None:
    eid = _captured()
    edited = ENTRY.model_copy(update={"what_to_do": "hold it and ask the Team Lead"})
    with TestClient(create_app()) as client:
        r = client.post(
            f"/capture/entries/{eid}/edit",
            json={"entry": edited.model_dump(mode="json"), "by": "owner-1"},
        )
        assert r.status_code == 202, r.text
        new_id = r.json()["episode_id"]
        assert new_id != eid
        again = client.post(
            f"/capture/entries/{eid}/edit",
            json={"entry": edited.model_dump(mode="json"), "by": "owner-1"},
        )
        assert again.status_code == 409  # only an entry still waiting can be edited
    drain(kinds=["apply_review", "parse_episode", "capture_entry"])
    with session_scope() as s:
        assert fstore.live_for_episode(s, eid, statuses=["pending", "current"]) == []
        (fact,) = fstore.live_for_episode(s, new_id, statuses=["pending"])
        assert "hold it and ask the Team Lead" in fact.statement
        by_id = {e["episode_id"]: e for e in cap.entries(s)}
        assert by_id[new_id]["edited_from"] == eid
        assert by_id[eid]["review"]["status"] == "rejected"


def test_the_rule_check_uses_the_rules_not_practice(seeded) -> None:
    seen: list[str] = []

    def fake(prompt, schema, **kw):  # noqa: ANN001, ANN202
        seen.append(prompt)
        return schema(verdict="conflict", rule=None, reason="the policy says 20 days")

    leave = ENTRY.model_copy(
        update={"subject": "Staff", "habit": "staff get 25 days of annual leave a year"}
    )
    with session_scope() as s:
        out = cap.check_rules(
            s, leave, structured_fn=fake, embed_fn=None, rerank_fn=lambda q, d: [1.0] * len(d)
        )
    assert out.verdict == "conflict" and out.rules
    assert "20 days" in seen[0]  # the rule in force was put in front of the model


def test_the_api_lists_questions_and_entries(seeded) -> None:
    _captured()
    with TestClient(create_app()) as client:
        q = client.get("/capture/questions").json()
        assert len(q["questions"]) == 5 and "Team Lead" in q["reviewers"]
        got = client.get("/capture/entries").json()
        assert got["entries"][0]["entry"]["subject"] == "Contoso Couriers"
        assert "known" in got
        m = client.post("/capture/match", json={"text": "Contoso Couriers"}).json()
        assert m["candidates"] and m["candidates"][0]["name"] == "Contoso Couriers"


# ---------------------------------------------------------------- Teams export


def _post(mid, at, name, text, reply=None):  # noqa: ANN001, ANN202
    return {
        "id": mid,
        "replyToId": reply,
        "messageType": "message",
        "createdDateTime": at,
        "from": {"user": {"displayName": name, "jobTitle": "AP Processor"}},
        "body": {"contentType": "html", "content": f"<p>{text}</p>"},
    }


EXPORT = {
    "team": "HR",
    "channel": "questions",
    "value": [
        _post("q1", "2026-05-04T09:00:00Z", "Ravi Kumar", "How many days of leave do I get?"),
        _post("q1r", "2026-05-04T09:05:00Z", "Asha Rao", "20, I think", reply="q1"),
        _post(
            "t1",
            "2026-05-04T10:00:00Z",
            "Asha Rao",
            "Most people take 22 days, they save the rest for the cash-out.",
        ),
        _post("n1", "2026-05-04T11:00:00Z", "Ravi Kumar", "Team lunch on Friday?"),
    ],
}


def fake_triage(prompt, schema, **kw) -> TriageOut:  # noqa: ANN001
    text = prompt.lower()
    if "lunch" in text:
        return TriageOut(reason="social", label="noise")
    if "most people take" in text:
        return TriageOut(reason="habit", label="tacit_tip")
    return TriageOut(reason="asks", label="question", question="How many leave days?")


def test_a_teams_export_is_triaged_thread_by_thread(seeded, monkeypatch) -> None:
    monkeypatch.setattr(ip, "_triage_structured", lambda: fake_triage)
    monkeypatch.setattr(get_settings(), "governance", True)
    asked: list[str] = []
    monkeypatch.setattr("app.answer.pipeline.ask", lambda q, **kw: asked.append(q) or {})
    eps = from_upload("hr_export.json", json.dumps(EXPORT).encode(), sender="owner-1")
    assert len(eps) == 3
    with session_scope() as s:
        ids = {e.meta["teams"]["thread"]: intake_submit(s, e)[0] for e in eps}
    drain(kinds=["parse_episode", "extract_episode"])
    with session_scope() as s:
        q = estore.get_episode(s, ids["q1"])
        assert (q.status, q.triage_label) == ("ignored", "question")
        assert q.meta["question"] == "How many leave days?"
        n = estore.get_episode(s, ids["n1"])
        assert (n.status, n.triage_label) == ("ignored", "noise")
        t = estore.get_episode(s, ids["t1"])
        assert t.triage_label == "tacit_tip" and t.status == "pending_review"
        assert t.sender == "Asha Rao" and t.meta["teams"]["uploaded_by"] == "owner-1"
        (src,) = estore.list_sources(s, ids["t1"])
        assert src.doc_type == "teams" and src.meta.get("practice") is True
        turns = [p for p in estore.passages_for_episode(s, ids["t1"]) if p.segment_kind == "turn"]
        assert [(p.speaker, p.locator) for p in turns] == [("Asha Rao", "[10:00]")]
        held = fstore.live_for_episode(s, ids["t1"], statuses=["pending"])
        assert held and all(f.kind == "practice" for f in held)
    assert asked == []  # a question from chat history is recorded, never answered again
