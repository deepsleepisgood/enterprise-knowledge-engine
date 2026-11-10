"""Governance (BUILD_PLAN Phase 9): inputs after setup wait for the process owner.

Uses the leave-policy corpus and fake extractor of test_graph_db (no network)."""

from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.core.db import session_scope
from app.govern import apply as gapply
from app.govern.policy import PENDING, PROVISIONAL, decide
from app.graph import pipeline as gp
from app.graph.compare import deterministic
from app.graph.ontology import SenderAuthority
from app.ingest.connectors import from_text
from app.ingest.intake import submit
from app.store import episodes as estore
from app.store import facts as fstore
from app.store import kb
from app.worker import drain
from tests.integration.test_graph_db import ONTO, V1, V2, fake_structured, graph  # noqa: F401

pytestmark = pytest.mark.db
DAYS = "annual_leave.days"


def _days(s) -> list[tuple[float, str]]:
    return sorted(
        (f.value["number"], f.status)
        for f in fstore.get_facts(s, attribute=DAYS)
        if not (f.scope or {}).get("client")
    )


def _send(text: str, sender: str, role: str) -> str:
    with session_scope() as s:
        eid, _ = submit(s, from_text(text, channel="upload", sender=sender, sender_role=role))
    drain(kinds=["parse_episode"])
    return eid


def _build_governed(eid: str) -> dict:
    return gp.extract_and_publish(
        eid, structured_fn=fake_structured, compare=deterministic, embed_fn=None, govern=True
    )


def _decide(item_id: int, decision: str, monkeypatch) -> dict:
    monkeypatch.setattr(gp, "_default_structured", lambda: None)  # deterministic resolution
    with session_scope() as s:
        item = kb.get_review_item(s, item_id)
        assert kb.decide_review_item(s, item_id, decision, "owner-1", row_version=item.row_version)
    return gapply.apply_decision(item_id)


def test_policy_decides_provisional_only_for_registered_low_risk() -> None:
    onto = ONTO.model_copy(deep=True)
    onto.sender_authority = [SenderAuthority(who="HR Director", client="all", topics=["all"])]
    ok = decide(onto, "asha@x.com", "HR Director", {"annual_leave"}, {"all"})
    assert ok.status == PROVISIONAL
    assert decide(onto, "bob@x.com", "Clerk", {"annual_leave"}, {"all"}).status == PENDING
    onto.topics[0].risk = "high"
    high = decide(onto, "asha@x.com", "HR Director", {"annual_leave"}, {"all"})
    assert high.status == PENDING and high.high_risk == ["annual_leave"]


def test_held_version_changes_nothing_until_approved(graph, monkeypatch) -> None:  # noqa: F811
    ingest, build = graph
    build(ingest(V1, "v1.md"))  # the owner's seeding: published at once
    monkeypatch.setattr(get_settings(), "governance", True)
    eid = _send(V2, "someone@x.com", "Clerk")
    out = _build_governed(eid)
    assert out["governance"] == PENDING and out["review_item"]
    with session_scope() as s:
        assert _days(s) == [(20.0, "current"), (24.0, "pending")]  # v1 still the rule
        assert estore.get_episode(s, eid).status == "pending_review"
        v2 = estore.list_sources(s, eid)[0]
        assert v2.status == PENDING  # its passages are not evidence for answers
        v1 = next(x for x in estore.list_sources(s) if x.version == "1.0")
        assert v1.status == "current"  # not superseded by a change nobody approved
    res = _decide(out["review_item"], "approved", monkeypatch)
    assert res["approved"] >= 1
    with session_scope() as s:
        days = _days(s)
        assert (24.0, "current") in days and (20.0, "current") not in days
        v1 = next(x for x in estore.list_sources(s) if x.version == "1.0")
        assert v1.status == "superseded"  # the deferred version link, made on approval
        assert estore.get_episode(s, eid).status == "published"
        assert any("approved by owner-1" in c.summary for c in kb.changes_since(s, 0))


def test_rejected_change_is_retracted(graph, monkeypatch) -> None:  # noqa: F811
    ingest, build = graph
    build(ingest(V1, "v1.md"))
    monkeypatch.setattr(get_settings(), "governance", True)
    eid = _send(V2, "someone@x.com", "Clerk")
    out = _build_governed(eid)
    _decide(out["review_item"], "rejected", monkeypatch)
    with session_scope() as s:
        assert _days(s) == [(20.0, "current")]
        assert estore.list_sources(s, eid)[0].status == "rejected"


def test_registered_sender_publishes_provisionally(graph, monkeypatch) -> None:  # noqa: F811
    ingest, build = graph
    build(ingest(V1, "v1.md"))
    with session_scope() as s:
        onto = dict(kb.active_schema(s).ontology)
        onto["sender_authority"] = [{"who": "HR Director", "client": "all", "topics": ["all"]}]
        kb.save_schema(s, onto, "induced", frozen_by="owner")  # the owner's Setup edit
    monkeypatch.setattr(get_settings(), "governance", True)
    eid = _send(V2, "asha@x.com", "HR Director")
    out = _build_governed(eid)
    assert out["governance"] == PROVISIONAL
    with session_scope() as s:
        assert (24.0, "provisional") in _days(s)  # answerable now, labelled provisional
        assert estore.list_sources(s, eid)[0].status == PROVISIONAL
    _decide(out["review_item"], "approved", monkeypatch)
    with session_scope() as s:
        assert (24.0, "current") in _days(s)
        assert estore.list_sources(s, eid)[0].status == "current"  # approved: in force
        assert any("approved by owner-1" in c.summary for c in kb.changes_since(s, 0))
