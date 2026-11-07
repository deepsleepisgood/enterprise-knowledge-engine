"""Schema evolution against the database: unplaced facts are re-keyed, history is kept."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from app.core.db import session_scope
from app.graph import evolve as ev
from app.graph import pipeline as gp
from app.graph.compare import deterministic
from app.graph.entities import Resolver
from app.graph.ontology import Attribute, Ontology, Topic
from app.graph.rules import get_rule
from app.store import entities, kb
from app.store import facts as fstore
from app.store.base import day_start

pytestmark = pytest.mark.db

ONTO = Ontology(
    topics=[Topic(key="payments", label="Payments")],
    attributes=[
        Attribute(
            key="payments.default_term_days",
            topic="payments",
            label="default payment term",
            value_type="days",
        )
    ],
)


def fake_llm(prompt, schema, **kw):
    if schema is ev._Pick:
        return schema(
            choice=1 if "payment" in prompt.split("Existing attributes")[0] else 0, reason="test"
        )
    groups = [ln for ln in prompt.splitlines() if ln.startswith("Group ")]
    return schema(
        attributes=[
            ev._NewAttribute(
                group=int(ln.split()[1].rstrip(":")),
                keep=True,
                topic="credit_notes",
                topic_label="Credit notes",
                parameter="days_to_raise",
                value_type="days",
            )
            for ln in groups
        ]
    )


def _other_fact(s, key: str, number: float, statement: str) -> int:
    other = entities.create(s, "topic", "Other")
    return fstore.insert(
        s,
        fstore.NewFact(
            origin_key=f"{key}:0",
            subject_id=other,
            attribute=key,
            value={"type": "days", "number": number, "unit": "days", "text": f"{number} days"},
            statement=statement,
            kind="rule",
            status="current",
            valid_from=day_start(date(2026, 4, 1)),
        ),
    )


def test_unplaced_facts_are_mapped_or_proposed_and_rekeyed(db) -> None:
    with session_scope() as s:
        kb.save_schema(s, ONTO.model_dump(), "induced", frozen_by="test")
        _other_fact(s, "other:default_payment_terms", 60, "Default payment term is 60 days.")
        _other_fact(s, "other:debit_note_days", 7, "Debit notes are raised within 7 days.")
        before = fstore.total_rows(s)
        started = datetime.now(UTC)

    out = gp.evolve_schema(auto_freeze=True, mode="induced", structured_fn=fake_llm, embed_fn=None)
    assert out["frozen"] and out["to_version"] == 2 and out["rekeyed"] == 2

    with session_scope() as s:
        onto = gp.active_ontology(s, "induced")
        assert onto.attribute("credit_notes.days_to_raise") is not None
        assert fstore.live_with_attribute_prefix(s, "other:") == []
        term = get_rule(s, onto, "payments", "default_term_days", today=date(2026, 11, 7))
        assert term.number == 60
        new = get_rule(s, onto, "credit_notes", "days_to_raise", today=date(2026, 11, 7))
        assert new.number == 7
        # Nothing was deleted: the old rows are retracted, still answerable as known before.
        assert fstore.total_rows(s) >= before + 2
        old = fstore.get_facts(s, attribute="other:default_payment_terms", known_at=started)
        assert [r.value["number"] for r in old] == [60]
        assert not [i for i in kb.list_review_items(s) if i.kind == "schema"]  # auto-approved


def test_without_auto_freeze_the_draft_waits_for_the_owner(db) -> None:
    with session_scope() as s:
        kb.save_schema(s, ONTO.model_dump(), "induced", frozen_by="test")
        _other_fact(s, "other:debit_note_days", 7, "Debit notes are raised within 7 days.")
    out = gp.evolve_schema(auto_freeze=False, mode="induced", structured_fn=fake_llm, embed_fn=None)
    assert not out["frozen"] and out["to_version"] == 2
    with session_scope() as s:
        assert gp.active_ontology(s, "induced").attribute("credit_notes.days_to_raise") is None
        assert len(fstore.live_with_attribute_prefix(s, "other:")) == 1
    again = gp.evolve_schema(
        auto_freeze=False, mode="induced", structured_fn=fake_llm, embed_fn=None
    )
    assert "draft waiting for review" in again["skipped"]
    applied = gp.apply_schema(2, "owner", structured_fn=fake_llm)
    assert applied["rekeyed"] == 1
    with session_scope() as s:
        assert fstore.live_with_attribute_prefix(s, "other:") == []


def test_apply_moves_topic_facts_to_the_new_topic_entity(db) -> None:
    with session_scope() as s:
        fid = _other_fact(s, "other:debit_note_days", 7, "Debit notes within 7 days.")
        onto = ONTO.model_copy(deep=True)
        onto.topics.append(Topic(key="credit_notes", label="Credit notes"))
        onto.attributes.append(
            Attribute(
                key="credit_notes.days_to_raise",
                topic="credit_notes",
                label="days to raise",
                value_type="days",
            )
        )
        moved, version = ev.apply(
            s,
            onto,
            {"other:debit_note_days": "credit_notes.days_to_raise"},
            deterministic,
            Resolver(s),
        )
        assert moved == 1 and version is not None
        (row,) = fstore.get_facts(s, attribute="credit_notes.days_to_raise")
        assert entities.get(s, row.subject_id).name == "Credit notes"
        assert row.meta["evolved_from"] == "other:debit_note_days" and row.id != fid
