"""Practice notes and the rules they are about (Teams-question fixes, 14 Nov).

- A retrieved practice note brings the rule on its topic into the evidence (rule anchors).
- The expert tip is a note the answer used, or one about the question; a data-row note about a
  named party is shown only when the answer relied on it.
- A calculator parameter added after the bind step binds to an attribute with exactly its key.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from app.answer import card as cards
from app.answer.retrieve import rule_anchors
from app.core.db import session_scope
from app.graph.ontology import Attribute, Ontology, Topic
from app.graph.rows import ORIGIN as ROW_ORIGIN
from app.graph.rules import RuleNotFound
from app.plugins.bindings import BoundRules
from app.store import entities, episodes, kb, search
from app.store import facts as fstore
from app.store.base import day_start

pytestmark = pytest.mark.db
TODAY = date(2026, 11, 14)


def _passage(s, sid: str, doc_type: str, kind: str, text: str) -> str:
    ep, _ = episodes.add_episode(
        s, channel="upload", content_hash=sid, received_at=datetime(2026, 11, 1, tzinfo=UTC)
    )
    episodes.upsert_source(
        s,
        {
            "id": sid,
            "episode_id": ep,
            "title": sid,
            "short_label": sid,
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
                "segment_kind": kind,
                "locator": "1",
                "section_title": sid,
                "text": text,
                "context_header": sid,
                "content_hash": pid,
                "meta": {"leaf": True},
            }
        ],
    )
    return pid


def _fact(
    s, pid: str, attr: str, statement: str, kind: str, origin: str | None = None, vec=None
) -> int:
    subj = entities.create(s, "topic", attr.split(".")[0])
    sid = pid.rsplit("-p", 1)[0]
    return fstore.insert(
        s,
        fstore.NewFact(
            origin_key=origin or f"{pid}:{attr}",
            subject_id=subj,
            attribute=attr,
            value={"type": "text", "text": statement},
            statement=statement,
            kind=kind,
            status="current",
            passage_id=pid,
            source_id=sid,
            valid_from=day_start(date(2026, 4, 1)),
            embedding=vec,
        ),
    )


def _unit(i: int) -> list[float]:
    v = [0.0] * 384
    v[i] = 1.0
    return v


def test_a_practice_note_brings_its_rule(db) -> None:
    with session_scope() as s:
        note = _passage(s, "talk", "interview", "turn", "I always wait for the late fee memo.")
        rule = _passage(s, "proc", "sop", "section", "Late fees are waived up to 3 days.")
        other = _passage(s, "proc2", "sop", "section", "Unrelated rule.")
        _fact(s, note, "late_fees.wait_habit", "Colleagues wait for the memo.", "practice")
        _fact(s, rule, "late_fees.waiver_days", "Late fees are waived up to 3 days.", "rule")
        _fact(s, other, "parking.spaces", "Unrelated rule.", "rule")
        hits = search.hydrate(s, [note, rule])
        assert rule_anchors(s, [hits[note]], [], None, TODAY, None, False) == [rule]
        # The rule is already in the evidence: nothing to add.
        assert rule_anchors(s, [hits[note], hits[rule]], [], None, TODAY, None, False) == []


def test_a_named_party_note_is_shown_only_when_the_answer_used_it(db) -> None:
    with session_scope() as s:
        row = _passage(s, "vendors", "dataset", "record", "Acme (V1): sends paper copies.")
        fid = _fact(
            s,
            row,
            "other:party_habits.note",
            "Acme (V1): sends paper copies.",
            "practice",
            origin=f"{ROW_ORIGIN}{row}:note",
        )
        named = list(fstore.by_ids(s, [fid]).values())
        common = dict(named=named, tips=[], ranked_passages=[], question_vec=None)
        assert cards.expert_tip(s, TODAY, cited=[], **common) is None
        tip = cards.expert_tip(s, TODAY, cited=[row], **common, row_origin=ROW_ORIGIN)
        assert tip and tip["text"].startswith("Acme (V1)")


def test_an_off_topic_note_in_a_retrieved_passage_is_not_the_tip(db) -> None:
    with session_scope() as s:
        talk = _passage(s, "talk", "interview", "turn", "Many topics in one answer.")
        _fact(s, talk, "parking.habit", "Arrive early for parking.", "practice")
        # Retrieved but not cited, and no similarity to the question: not shown.
        tip = cards.expert_tip(
            s, TODAY, cited=[], named=[], tips=[], ranked_passages=[talk], question_vec=None
        )
        assert tip is None


ONTO = Ontology(
    topics=[Topic(key="late_fees", label="Late fees")],
    attributes=[
        Attribute(key="late_fees.waiver_days", topic="late_fees", label="waiver", value_type="days")
    ],
)


def _rule(s) -> None:
    fstore.insert(
        s,
        fstore.NewFact(
            origin_key="late",
            subject_id=entities.create(s, "topic", "Late fees"),
            attribute="late_fees.waiver_days",
            value={"type": "days", "number": 3, "unit": "days", "text": "3 days"},
            statement="Late fees are waived up to 3 days.",
            kind="rule",
            status="current",
            valid_from=day_start(date(2026, 4, 1)),
        ),
    )


def test_an_unbound_parameter_uses_the_attribute_with_its_exact_key(db) -> None:
    with session_scope() as s:
        _rule(s)
        rv = BoundRules(s, ONTO, "ap", today=TODAY).get("late_fees", "waiver_days")
        assert rv.number == 3


def test_a_parameter_the_bind_step_left_unresolved_stays_unresolved(db) -> None:
    with session_scope() as s:
        _rule(s)
        kb.put_binding(
            s, "ap", "late_fees.waiver_days", attribute_key=None, confidence=0.0, confirmed_by=None
        )
        with pytest.raises(RuleNotFound):
            BoundRules(s, ONTO, "ap", today=TODAY).get("late_fees", "waiver_days")


def test_the_tip_is_the_note_the_answer_used_from_a_many_topic_passage(db) -> None:
    with session_scope() as s:
        talk = _passage(
            s, "talk", "interview", "turn", "Site A batches receipts; B invoices early."
        )
        _fact(
            s,
            talk,
            "habits.site_batching",
            "Site A batches receipts on Monday.",
            "practice",
            vec=_unit(1),
        )
        _fact(
            s,
            talk,
            "habits.early_invoices",
            "Supplier B invoices before dispatch.",
            "practice",
            vec=_unit(2),
        )
        common = dict(
            cited=[talk], named=[], tips=[], ranked_passages=[talk], question_vec=_unit(2)
        )
        # The question looks like note 2, but the answer used note 1 from this passage.
        tip = cards.expert_tip(s, TODAY, **common, used_vecs={talk: _unit(1)})
        assert tip and tip["text"].startswith("Site A")


def test_a_procedure_found_in_part_is_completed(db) -> None:
    from app.answer.retrieve import missing_steps

    with session_scope() as s:
        ep, _ = episodes.add_episode(
            s, channel="upload", content_hash="proc", received_at=datetime(2026, 11, 1, tzinfo=UTC)
        )
        episodes.upsert_source(
            s,
            {
                "id": "proc",
                "episode_id": ep,
                "title": "Procedure",
                "short_label": "Procedure",
                "doc_type": "sop",
                "status": "current",
                "dated": date(2026, 4, 1),
            },
        )
        rows = [
            {
                "id": f"proc-{n}",
                "source_id": "proc",
                "episode_id": ep,
                "ordinal": n,
                "segment_kind": "step",
                "locator": f"8.2, step {n}",
                "section_title": "Changes",
                "text": f"Step {n} of the change procedure.",
                "context_header": "Procedure 8.2",
                "content_hash": f"proc-{n}",
                "meta": {"leaf": True},
            }
            for n in range(1, 5)
        ]
        episodes.upsert_passages(s, rows)
        hits = search.hydrate(s, ["proc-1", "proc-3", "proc-4"])
        assert missing_steps(s, [hits["proc-1"], hits["proc-3"], hits["proc-4"]]) == ["proc-2"]
        # One step on its own is not filled in.
        assert missing_steps(s, [hits["proc-3"]]) == []


def test_a_scope_with_rules_but_no_client_entity_is_offered_to_the_router(db) -> None:
    from app.answer.pipeline import known_clients

    with session_scope() as s:
        entities.create(s, "client", "Group Co")
        ep, _ = episodes.add_episode(
            s, channel="upload", content_hash="memo", received_at=datetime(2026, 11, 1, tzinfo=UTC)
        )
        episodes.upsert_source(
            s,
            {
                "id": "memo",
                "episode_id": ep,
                "title": "Memo",
                "short_label": "Memo",
                "doc_type": "memo",
                "status": "current",
                "client_scope": "Retail Co",
                "dated": date(2026, 4, 1),
            },
        )
        assert known_clients(s) == ["Group Co", "Retail Co"]
