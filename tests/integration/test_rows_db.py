"""Facts from data rows (app/graph/rows.py): a plug-in's notes about counterparties become
practice facts citing their row; reloads are idempotent, changes retire the old fact, and a
question naming the counterparty gets the note as evidence."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from app.answer.retrieve import retrieve
from app.core.db import session_scope
from app.graph.rows import RowFact, publish_row_facts
from app.store import entities, episodes, facts, kb
from app.store.base import use_tenant
from tests.integration.test_answer_db import fake_embed

pytestmark = pytest.mark.db

T = "rows_t"


def _export(s, rows: dict[int, str], tag: str = "export", day: date = date(2026, 10, 28)) -> str:
    """An episode with one source and one record passage per row (row number -> text)."""
    ep, _ = episodes.add_episode(
        s,
        channel="upload",
        content_hash=tag,
        received_at=datetime(day.year, day.month, day.day, tzinfo=UTC),
    )
    src = f"{tag}-src"
    episodes.upsert_source(
        s,
        {
            "id": src,
            "episode_id": ep,
            "title": f"Operations export {tag}",
            "short_label": f"Ops {tag}",
            "doc_type": "spreadsheet",
            "status": "current",
            "dated": day,
        },
    )
    episodes.upsert_passages(
        s,
        [
            {
                "id": f"{tag}-row-{n}" if tag != "export" else f"row-{n}",
                "source_id": src,
                "episode_id": ep,
                "ordinal": n,
                "segment_kind": "record",
                "locator": f"partners row {n}",
                "section_title": "partners",
                "text": text,
                "context_header": f"Ops {tag} · partners row {n}",
                "content_hash": f"{tag}-h{n}",
                "meta": {"leaf": True},
            }
            for n, text in rows.items()
        ],
    )
    return ep


def _note(n: int, name: str, note: str) -> RowFact:
    return RowFact(
        subject=f"{name} (P{n})",
        subject_type="counterparty",
        aliases=[name, f"P{n}"],
        attribute="partner_habits.note",
        statement=f"{name} (P{n}): {note}",
        locator=f"partners row {n}",
    )


@pytest.fixture
def export(db):
    with use_tenant(T), session_scope() as s:
        episodes.delete_tenant_content(s)  # the db fixture resets the default tenant only
        ep = _export(
            s,
            {
                1: "id: P1; name: Zephyr Freight; note: re-sends invoices with a /A suffix",
                2: "id: P2; name: Quill Paper; note: ",
                3: "id: P3; name: Orbit Metals; note: invoices before dispatch",
            },
        )
    return ep


def test_row_notes_become_cited_practice_facts_and_reloads_change_nothing(export) -> None:
    items = [_note(1, "Zephyr Freight", "re-sends invoices with a /A suffix")]
    items.append(_note(3, "Orbit Metals", "invoices before dispatch"))
    with use_tenant(T), session_scope() as s:
        v0 = kb.current_kb_version(s)
        out = publish_row_facts(s, None, export, items, approved=True)
    assert out["added"] == 2 and not out["missing_rows"]
    with use_tenant(T), session_scope() as s:
        live = [f for f in facts.get_facts(s) if f.kind == "practice"]
        assert {f.passage_id for f in live} == {"row-1", "row-3"}  # each cites its own row
        assert all(f.status == "current" and f.attribute.startswith("other:") for f in live)
        eid = entities.by_alias(s, "Zephyr Freight")
        assert eid and entities.by_alias(s, "P1") == eid
        assert kb.current_kb_version(s) > v0  # one new version (ids are shared by tenants)
        again = publish_row_facts(s, None, export, items, approved=True)
    assert again["unchanged"] == 2 and again["added"] == again["changed"] == 0


def test_a_changed_note_retires_the_old_fact_and_a_removed_note_is_retired(export) -> None:
    first = [_note(1, "Zephyr Freight", "re-sends invoices with a /A suffix")]
    first.append(_note(3, "Orbit Metals", "invoices before dispatch"))
    with use_tenant(T), session_scope() as s:
        publish_row_facts(s, None, export, first, approved=True)
    later = [_note(1, "Zephyr Freight", "re-sends invoices with a -REV suffix")]  # row 3 gone
    with use_tenant(T), session_scope() as s:
        out = publish_row_facts(s, None, export, later, approved=True)
    assert out["changed"] == 1 and out["retired"] == 1
    with use_tenant(T), session_scope() as s:
        live = [f for f in facts.get_facts(s) if f.kind == "practice"]
        assert [f.statement for f in live] == [
            "Zephyr Freight (P1): re-sends invoices with a -REV suffix"
        ]
        assert live[0].supersedes_id is not None  # history kept: the old row is retracted
        changes = kb.changes_since(s, 0)
        assert any("/A suffix -> " in c.summary for c in changes)


def test_unapproved_row_notes_are_held_for_the_owner(export) -> None:
    with use_tenant(T), session_scope() as s:
        out = publish_row_facts(
            s, None, export, [_note(1, "Zephyr Freight", "re-sends with /A")], approved=False
        )
    assert out["held"] == 1
    with use_tenant(T), session_scope() as s:
        held = [f for f in facts.get_facts(s, statuses=["pending"]) if f.kind == "practice"]
        assert len(held) == 1 and [r.kind for r in kb.list_review_items(s)] == ["change"]
        assert not [f for f in facts.get_facts(s, statuses=["current"]) if f.kind == "practice"]


def test_a_question_naming_the_counterparty_gets_its_note_as_evidence(export) -> None:
    items = [_note(1, "Zephyr Freight", "re-sends invoices with a /A suffix")]
    with use_tenant(T), session_scope() as s:
        publish_row_facts(s, None, export, items, approved=True)
        # Practice stated in a document (not a data row) about a named entity: search finds its
        # passage as before; it is not promoted to evidence.
        orbit = entities.create(s, "counterparty", "Orbit Metals")
        facts.insert(
            s,
            facts.NewFact(
                origin_key="doc:interview:1",
                subject_id=orbit,
                attribute="other:habit",
                value={"type": "text", "text": "batches deliveries"},
                statement="Orbit Metals batches deliveries.",
                kind="practice",
                status="current",
            ),
        )
    with use_tenant(T), session_scope() as s:
        got = retrieve(
            s,
            "What does Zephyr Freight do when it re-sends an invoice?",
            today=date(2026, 11, 13),
            embed_fn=fake_embed,
            rerank_fn=None,
        )
        other = retrieve(
            s, "What does Orbit Metals do?", today=date(2026, 11, 13), embed_fn=fake_embed
        )
    assert [f.passage_id for f in got.named_practice] == ["row-1"]
    assert other.named_practice == []  # no note was published for it


FIRST = [
    _note(1, "Zephyr Freight", "re-sends invoices with a /A suffix"),
    _note(3, "Orbit Metals", "invoices before dispatch"),
]
NOV = {
    1: "id: P1; name: Zephyr Freight; note: re-sends invoices with a /A suffix",
    2: "id: P2; name: Quill Paper; note: re-sends invoices with a -REV suffix",
}


def _live_practice(s) -> dict[str, str]:
    return {f.statement: f.passage_id for f in facts.get_facts(s) if f.kind == "practice"}


def test_a_newer_export_file_replaces_the_older_files_notes(export) -> None:
    with use_tenant(T), session_scope() as s:
        publish_row_facts(s, None, export, FIRST, approved=True)
        nov = _export(s, NOV, tag="nov", day=date(2026, 11, 10))
    later = [
        _note(1, "Zephyr Freight", "re-sends invoices with a /A suffix"),  # same note
        _note(2, "Quill Paper", "re-sends invoices with a -REV suffix"),  # new supplier
    ]  # Orbit Metals (row 3 of the October file) is not in November's
    with use_tenant(T), session_scope() as s:
        out = publish_row_facts(s, None, nov, later, approved=True)
    assert (out["carried"], out["added"], out["retired"]) == (1, 1, 1)
    with use_tenant(T), session_scope() as s:
        assert _live_practice(s) == {
            "Zephyr Freight (P1): re-sends invoices with a /A suffix": "nov-row-1",
            "Quill Paper (P2): re-sends invoices with a -REV suffix": "nov-row-2",
        }
        assert any("Orbit Metals" in c.summary for c in kb.changes_since(s, 0))


def test_an_older_export_loaded_late_changes_nothing(export) -> None:
    with use_tenant(T), session_scope() as s:
        nov = _export(s, NOV, tag="nov", day=date(2026, 11, 10))
        publish_row_facts(s, None, nov, [_note(1, "Zephyr Freight", "x")], approved=True)
        out = publish_row_facts(s, None, export, FIRST, approved=True)  # dated 28 Oct
    assert out["stale"] and out["added"] == 0
    with use_tenant(T), session_scope() as s:
        assert _live_practice(s) == {"Zephyr Freight (P1): x": "nov-row-1"}


def test_a_held_newer_export_keeps_the_old_notes_until_approved(export) -> None:
    with use_tenant(T), session_scope() as s:
        publish_row_facts(s, None, export, FIRST, approved=True)
        nov = _export(s, NOV, tag="nov", day=date(2026, 11, 10))
        old_ids = sorted(f.id for f in facts.get_facts(s) if f.kind == "practice")
        out = publish_row_facts(
            s, None, nov, [_note(1, "Zephyr Freight", "re-sends with -REV")], approved=False
        )
    assert out["held"] == 1 and out["retired"] == 1
    with use_tenant(T), session_scope() as s:
        assert sorted(f.id for f in facts.get_facts(s, statuses=["current"])) == old_ids
        (item,) = kb.list_review_items(s)
        assert sorted(item.payload["retire_fact_ids"]) == old_ids  # retired on approval
