"""Distribution (Phase 11): answer recall and the live update stream.

When a change retires or replaces a fact, everyone whose answer in the 7 days before cited any
version of that fact is told once per change; answers about a past date, evaluation runs and
anonymous askers are not. A
rejected provisional change is recalled the same way. `/stream` sends the state pages refetch on.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient

from app.api import changes as changes_api
from app.api.main import create_app
from app.core.db import session_scope
from app.distribute.recall import recall
from app.store import answers as astore
from app.store import entities, jobs, kb
from app.store import facts as fstore
from app.store.models import Job

pytestmark = pytest.mark.db


def _fact(s, key: str, text: str, status: str = "current") -> int:
    subj = entities.create(s, "topic", "Price tolerance")
    return fstore.insert(
        s,
        fstore.NewFact(
            origin_key=key,
            subject_id=subj,
            attribute="tolerance_pct",
            value={"type": "text", "text": text},
            statement=f"Price tolerance is {text}.",
            kind="rule",
            status=status,
            valid_from=datetime(2026, 4, 1, tzinfo=UTC),
        ),
    )


def _answer(s, user: str, cited: list[int], as_of: date | None = None, q: str = "") -> int:
    return astore.log_answer(
        s,
        user_id=user,
        question=q or f"What is the price tolerance? ({user})",
        client=None,
        as_of=as_of,
        kb_version=kb.current_kb_version(s),
        route="lookup",
        card={},
        cited_fact_ids=cited,
        cited_passage_ids=[],
        latency_ms=1,
    )


def _queued(s, kind: str) -> int:
    from sqlalchemy import func, select

    return s.scalar(select(func.count(Job.id)).where(Job.kind == kind, Job.status == "queued"))


def test_a_replaced_rule_recalls_the_answers_that_cited_it(db) -> None:
    with session_scope() as s:
        old = _fact(s, "doc:sop:1", "1%")
        other = _fact(s, "doc:sop:2", "₹500 cap")
        _answer(s, "alice", [old], q="An earlier question")
        _answer(s, "alice", [old], q="What tolerance applies to Arvana?")  # one note, latest
        _answer(s, "anonymous", [old])  # nobody to tell
        _answer(s, "eval-run-7", [old])  # evaluation runs are never recalled
        _answer(s, "bob", [old], as_of=date(2026, 5, 1))  # asked about the past
        _answer(s, "carol", [other])  # cited something else
    with session_scope() as s:
        # Resolution closes the old fact's interval: a revision with a new id.
        closed = fstore.revise(s, old, valid_to=datetime(2026, 11, 1, tzinfo=UTC))
        new = _fact(s, "email:fc:1", "2%")
        v = kb.bump_kb_version(s, "email from the FC")
        kb.record_change(s, v, "Price tolerance: 1% -> 2%", new_fact=new, old_fact=closed)
        assert _queued(s, "answer_recall") == 1  # queued with the change, same transaction
    with session_scope() as s:
        out = recall(s)
    assert out == {"changes": 1, "notified": 1}
    with session_scope() as s:
        (note,) = astore.notifications_for(s, "alice", unread_only=True)
        assert note["kind"] == "recall" and note["question"] == "What tolerance applies to Arvana?"
        assert "1% -> 2%" in note["body"] and note["change_id"] is not None
        others = ("eval-run-7", "bob", "carol", "anonymous")
        assert all(not astore.notifications_for(s, u) for u in others)
        assert astore.unread_count(s, "alice") == 1
        assert recall(s)["notified"] == 0  # idempotent


def test_an_answer_saved_after_the_change_but_built_before_it_is_recalled(db) -> None:
    """The 12 s race: an answer read the old rule, the change was published and its recall ran,
    then the answer was saved. It is recalled because it cited a row the change replaced, not
    by when it was saved; an answer citing a later revision in the same lineage is not."""
    with session_scope() as s:
        old = _fact(s, "doc:sop:1", "1%")
    with session_scope() as s:
        closed = fstore.revise(s, old, valid_to=datetime(2026, 11, 1, tzinfo=UTC))
        new = _fact(s, "email:fc:1", "2%")
        v = kb.bump_kb_version(s, "SOP v4")
        kb.record_change(s, v, "Price tolerance: 1% -> 2%", new_fact=new, old_fact=closed)
    with session_scope() as s:
        later = fstore.revise(s, closed, confidence=0.9)  # same lineage, a later version
        kb.bump_kb_version(s, "confidence recalibrated")
    with session_scope() as s:
        assert recall(s)["notified"] == 0  # the worker ran before the answer was saved
        _answer(s, "fay", [old], q="Asked at 12:02:55")  # saved 12:03:08, after the change
        _answer(s, "gil", [later], q="Asked after the change")
    with session_scope() as s:
        assert recall(s)["notified"] == 1
        (note,) = astore.notifications_for(s, "fay")
        assert note["question"] == "Asked at 12:02:55"
        assert not astore.notifications_for(s, "gil")


def test_publishes_committing_out_of_version_order_are_recalled(db) -> None:
    """Publishes take no lock, so two of them can commit out of id order: A takes version N,
    B takes N+1 and commits first. An answer then sees N+1 but not N, and relies on the rule A
    is about to replace. It is still recalled for A (and nothing waited on anything)."""
    with session_scope() as s:
        x = _fact(s, "doc:sop:x", "1%")
        y = _fact(s, "doc:sop:y", "₹500 cap")
    with session_scope() as a:  # publish A: open while B commits and the answer is given
        closed_x = fstore.revise(a, x, valid_to=datetime(2026, 11, 1, tzinfo=UTC))
        va = kb.bump_kb_version(a, "A")
        kb.record_change(a, va, "Tolerance: 1% -> 2%", old_fact=closed_x)
        with session_scope() as b:
            closed_y = fstore.revise(b, y, valid_to=datetime(2026, 11, 1, tzinfo=UTC))
            vb = kb.bump_kb_version(b, "B")
            kb.record_change(b, vb, "Cap: ₹500 -> ₹1,000", old_fact=closed_y)
        assert vb > va
        with session_scope() as s:
            assert kb.current_kb_version(s) == vb  # sees N+1 without N
            _answer(s, "hal", [x])  # x is still in force for this reader
    with session_scope() as s:
        recall(s)
        (note,) = astore.notifications_for(s, "hal")
        assert "1% -> 2%" in note["body"]


def test_a_shared_snapshot_does_not_see_a_change_published_meanwhile(db) -> None:
    from app.core.db import export_snapshot, snapshot_scope

    with session_scope() as s:
        kb.bump_kb_version(s, "v1")
    with snapshot_scope(writable=True) as answer:
        seen = kb.current_kb_version(answer)
        snap = export_snapshot(answer)
        with session_scope() as owner:
            kb.bump_kb_version(owner, "approved meanwhile")
        with snapshot_scope(snapshot=snap) as search:  # the parallel search joins it
            assert kb.current_kb_version(search) == seen
        assert kb.current_kb_version(answer) == seen
    with session_scope() as s:
        assert kb.current_kb_version(s) > seen
    with pytest.raises(Exception, match="snapshot"), snapshot_scope(snapshot=snap) as late:
        kb.current_kb_version(late)  # the answer's transaction has ended


def test_a_rejected_provisional_change_recalls_answers_that_relied_on_it(db) -> None:
    from app.govern import apply as gapply

    with session_scope() as s:
        prov = _fact(s, "email:fc:2", "3%", status="provisional")
        _answer(s, "dan", [prov])
        item = kb.add_review_item(s, "change", {"fact_ids": [prov], "status": "provisional"})
        assert kb.decide_review_item(s, item, "rejected", "owner-1")
    gapply.apply_decision(item)
    with session_scope() as s:
        withdrawn = [c for c in kb.changes_since(s, 0) if c.old_fact == prov]
        assert withdrawn and withdrawn[0].summary.startswith("Withdrawn:")
        recall(s)
        (note,) = astore.notifications_for(s, "dan")
        assert note["change_id"] == withdrawn[0].id


def test_the_change_feed_labels_a_retired_fact(db) -> None:
    with session_scope() as s:
        f = _fact(s, "row:p1:note", "a habit")
        fstore.retract(s, f)
        v = kb.bump_kb_version(s, "export")
        kb.record_change(s, v, "Retired: a habit", old_fact=f)
    with TestClient(create_app()) as client:
        feed = client.get("/changes").json()
    assert [c["status"] for c in feed if c["summary"] == "Retired: a habit"] == ["retired"]


def test_stream_sends_the_state_pages_refetch_on(db, monkeypatch) -> None:
    monkeypatch.setattr(changes_api, "STREAM_LIFETIME_S", 0.5)
    monkeypatch.setattr(changes_api, "STREAM_POLL_S", 0.1)
    with session_scope() as s:
        astore.notify(s, "erin", "recall", "A rule changed")
        jobs.enqueue(s, "noop", {})
    with (
        TestClient(create_app()) as client,
        client.stream("GET", "/stream", params={"user_id": "erin"}) as res,
    ):
        assert res.headers["content-type"].startswith("text/event-stream")
        body = "".join(res.iter_text())
    assert body.startswith("retry: 3000")
    data = [ln[6:] for ln in body.splitlines() if ln.startswith("data: ")]
    state = json.loads(data[0])
    assert state["unread"] == 1 and "kb_version" in state and "episodes" in state
    assert len(data) == 1  # nothing moved: one event, then keep-alive comments
