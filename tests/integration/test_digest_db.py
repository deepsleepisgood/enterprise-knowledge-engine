"""Distribution (Phase 11): the daily digest and the drafted edit to a document still in force.

A procedure (source A, current) says the tolerance is 1%. A memo (source B) changes it to 2% for
one client. The digest of that day lists the change with its values, source and acknowledgement
count, says a document needs editing, and what this user has not acknowledged. The document edit
is drafted for A's passage (here by a fake model) and checked without the model.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.core.db import session_scope
from app.distribute import document_edit as de
from app.distribute.digest import build_digest
from app.store import entities, episodes, kb
from app.store import facts as fstore
from app.store.base import utcnow

pytestmark = pytest.mark.db

PASSAGE = (
    "4.2 Price tolerance\n\nAn invoice line passes when its price is within 1% of the PO price, "
    "capped at 500 per line. Larger differences go to the buyer."
)


def _source(s, sid: str, label: str, doc_type: str, text: str) -> tuple[str, str]:
    ep, _ = episodes.add_episode(
        s, channel="upload", content_hash=sid, received_at=datetime(2026, 11, 1, tzinfo=UTC)
    )
    episodes.upsert_source(
        s,
        {
            "id": sid,
            "episode_id": ep,
            "title": label,
            "short_label": label,
            "doc_type": doc_type,
            "status": "current",
            "dated": date(2026, 4, 1),
        },
    )
    pid = f"{sid}-p1"
    episodes.upsert_passages(
        s,
        [
            {
                "id": pid,
                "source_id": sid,
                "episode_id": ep,
                "ordinal": 1,
                "segment_kind": "section",
                "locator": "4.2",
                "section_title": "Price tolerance",
                "text": text,
                "context_header": f"{label} · 4.2",
                "content_hash": pid,
                "meta": {"leaf": True},
            }
        ],
    )
    return ep, pid


def _fact(s, key, ep, sid, pid, text, client=None, status="current") -> int:
    subj = entities.create(s, "topic", "Price tolerance")
    return fstore.insert(
        s,
        fstore.NewFact(
            origin_key=key,
            subject_id=subj,
            attribute="price_tolerance.pct",
            value={
                "type": "percentage",
                "text": text,
                "number": float(text.rstrip("%")),
                "unit": "%",
            },
            statement=f"The price tolerance is {text}"
            + (f" for {client}." if client else " of the PO price."),
            kind="rule",
            status=status,
            scope={"client": client} if client else {},
            passage_id=pid,
            episode_id=ep,
            source_id=sid,
            valid_from=datetime(2026, 11, 16, tzinfo=UTC),
        ),
    )


@pytest.fixture
def changed(db) -> dict[str, int]:
    with session_scope() as s:
        ep_a, p_a = _source(s, "sop-a", "Procedure v4", "sop", PASSAGE)
        ep_b, p_b = _source(s, "memo-b", "Memo CX-1", "memo", "For Client X the tolerance is 2%.")
        old = _fact(s, "doc:a:1", ep_a, "sop-a", p_a, "1%")
        new = _fact(s, "doc:b:1", ep_b, "memo-b", p_b, "2%", client="Client X")
        closed = fstore.revise(s, old, valid_to=datetime(2026, 11, 16, tzinfo=UTC))
        v = kb.bump_kb_version(s, "memo")
        rule = kb.record_change(
            s,
            v,
            "Tolerance for Client X: 1% -> 2%",
            new_fact=new,
            old_fact=closed,
            effective_at=datetime(2026, 11, 16, tzinfo=UTC),
        )
        kb.record_change(s, v, "extraction of abc: 2 new, 0 revised, 0 retired facts")
        prov = _fact(s, "email:c:1", ep_b, "memo-b", p_b, "3%", status="provisional")
        v2 = kb.bump_kb_version(s, "email")
        provisional = kb.record_change(s, v2, "Tolerance 2% -> 3%", new_fact=prov, old_fact=new)
    return {"rule": rule, "provisional": provisional}


def test_digest_lists_the_days_changes_and_what_the_user_has_not_seen(changed) -> None:
    today = utcnow().date()
    with session_scope() as s:
        d = build_digest(s, today, 0, user_id="ana", users=4)
    assert [i["id"] for i in d["rules"]] == [changed["rule"], changed["provisional"]]
    assert d["updates"] == 1 and d["document_edits"] == [changed["rule"]]
    assert d["to_acknowledge"] == [changed["rule"], changed["provisional"]]
    assert (
        "Price tolerance: 1% -> 2% (from 16 Nov 2026; source: Memo CX-1; seen by 0 of 4)"
        in (d["text"])
    )
    assert "provisional, awaiting the owner" in d["text"]
    assert "1 change(s) need an edit to a document still in force" in d["text"]
    with session_scope() as s:
        kb.ack_change(s, changed["rule"], "ana")
        again = build_digest(s, today, 0, user_id="ana", users=4)
        assert again["to_acknowledge"] == [changed["provisional"]]
        yesterday = build_digest(s, today - timedelta(days=1), 0)
    assert yesterday["empty"] and yesterday["text"].endswith("No changes to the knowledge base.")


def _fake(revised: str):
    def structured(prompt, schema, **kw):
        assert "Current passage:" in prompt and "only to Client X" in prompt
        assert kw["prompt_version"] == de.PROMPT_VERSION
        return schema(revised_text=revised, summary="Added the Client X exception.")

    return structured


def test_document_edit_is_drafted_for_the_passage_and_checked(changed) -> None:
    revised = PASSAGE.replace(
        "capped at 500 per line.",
        "capped at 500 per line. For Client X the tolerance is 2% from 16 Nov 2026.",
    )
    with session_scope() as s:
        out = de.draft_document_edit(s, changed["rule"], structured_fn=_fake(revised))
    assert out["document"] == "Procedure v4" and out["locator"] == "4.2"
    assert out["verified"] and not out["problems"]
    inserted = "".join(r["text"] for r in out["diff"] if r["op"] == "insert")
    assert "For Client X the tolerance is 2%" in inserted
    assert not [r for r in out["diff"] if r["op"] == "delete"]  # nothing else touched


def test_a_draft_without_the_new_value_is_flagged(changed) -> None:
    with session_scope() as s:
        out = de.draft_document_edit(s, changed["rule"], structured_fn=_fake(PASSAGE))
    assert not out["verified"]
    assert any("new value (2%)" in p for p in out["problems"])
    assert any("same as the current text" in p for p in out["problems"])


def test_no_edit_for_a_provisional_change_and_the_api_says_why(changed, monkeypatch) -> None:
    with session_scope() as s, pytest.raises(de.EditNotNeeded):
        de.draft_document_edit(s, changed["provisional"], structured_fn=_fake("x"))
    with TestClient(create_app()) as client:
        r = client.post(f"/changes/{changed['provisional']}/document-edit")
        assert r.status_code == 409
        feed = {c["id"]: c for c in client.get("/changes").json()}
        assert feed[changed["rule"]]["document_edit"] == {
            "document": "Procedure v4",
            "locator": "4.2",
        }
        assert feed[changed["provisional"]]["document_edit"] is None
        d = client.get("/digest", params={"user_id": "ana"}).json()
        assert d["document_edits"] == [changed["rule"]] and "Changes on" in d["text"]
        monkeypatch.setattr("app.core.llm.structured", _fake(PASSAGE + " For Client X: 2%."))
        ok = client.post(f"/changes/{changed['rule']}/document-edit").json()
        assert ok["verified"] and ok["suggested_text"].endswith("For Client X: 2%.")


def test_value_terms_long_text_checks_figures_only() -> None:
    assert de._terms("2%") == ["2%"]
    long = "Quantity tolerance applies only to the four listed materials, up to 7% above the GRN."
    assert de._terms(long) == ["7%"]  # wording may differ, the figure may not
    assert de._terms("Applies only to the listed materials; all others have none at all.") == []


def test_value_terms_skip_version_tags_and_full_stops() -> None:
    long = (
        "Applies to the four materials in the memo; others follow SOP v4.0 section 4.3 with none."
    )
    assert de._terms(long) == ["4.3"]


def test_the_feed_remembers_what_this_user_acknowledged(changed) -> None:
    with TestClient(create_app()) as client:
        rule = changed["rule"]
        assert client.post(f"/changes/{rule}/ack", json={"user_id": "ana"}).status_code == 200
        mine = {c["id"]: c for c in client.get("/changes", params={"user_id": "ana"}).json()}
        other = {c["id"]: c for c in client.get("/changes", params={"user_id": "ben"}).json()}
        anon = {c["id"]: c for c in client.get("/changes").json()}
    assert mine[rule]["seen"] and not mine[changed["provisional"]]["seen"]
    assert not other[rule]["seen"] and not anon[rule]["seen"]
    assert mine[rule]["acknowledged"] == 1
