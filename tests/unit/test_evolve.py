"""Schema evolution logic: grouping, mapping and proposing without a database (fake LLM)."""

from __future__ import annotations

from datetime import UTC, datetime

from app.graph import evolve as ev
from app.graph.ontology import Attribute, Ontology, Topic
from app.store.facts import FactRow


def row(key: str, statement: str, vtype: str = "days", number: float | None = 5) -> FactRow:
    return FactRow(
        id=abs(hash((key, statement))) % 10_000,
        origin_key=f"{key}:{statement}",
        subject_id="topic-other",
        attribute=key,
        value={"type": vtype, "number": number, "text": statement},
        scope={},
        statement=statement,
        kind="rule",
        status="current",
        valid_from=None,
        valid_to=None,
        recorded_at=datetime(2026, 11, 7, tzinfo=UTC),
        retracted_at=None,
        authority_rank=2,
    )


ONTO = Ontology(
    topics=[Topic(key="payments", label="Payments")],
    attributes=[
        Attribute(
            key="payments.default_term_days",
            topic="payments",
            label="default payment term",
            value_type="days",
            description="days until payment when nothing else applies",
        )
    ],
)


def fake_embed(texts: list[str]) -> list[list[float]]:
    """Three-dimensional 'embedding': payment terms, document versions, everything else."""
    out = []
    for t in texts:
        t = t.lower()
        if "term" in t or "payment" in t:
            out.append([1.0, 0.0, 0.0])
        elif "version" in t:
            out.append([0.0, 0.0, 1.0])
        else:
            out.append([0.0, 1.0, 0.0])
    return out


def test_group_merges_names_that_mean_the_same() -> None:
    by_key = {
        "other:default_payment_terms_days": [
            row("other:default_payment_terms_days", "Default payment term is 60 days.")
        ],
        "other:payment_term_default": [row("other:payment_term_default", "Pay in 60 days.")],
        "other:credit_note_link": [
            row("other:credit_note_link", "Credit notes quote the original invoice.", "text", None)
        ],
    }
    groups = ev.group(by_key, fake_embed)
    sizes = sorted(len(g.keys) for g in groups)
    assert sizes == [1, 2]
    assert ev.group(by_key, None) and len(ev.group(by_key, None)) == 3  # no embeddings: by name


def test_value_types_must_be_compatible_to_merge_or_map() -> None:
    assert ev._compatible("days", "number") and not ev._compatible("days", "list")
    g = ev.Group(["other:payment_text"], [row("other:payment_text", "payment", "list")], "list")
    assert ev._candidates(g, ONTO, [1.0, 0.0, 0.0], [[1.0, 0.0, 0.0]]) == []


def test_clean_key_refuses_time_scope_and_other() -> None:
    assert ev._clean_key("Credit Notes", "Link To Invoice") == ("credit_notes", "link_to_invoice")
    assert ev._clean_key("payments", "old_term_days") is None
    assert ev._clean_key("payments", "general_term_days") == ("payments", "term_days")
    assert ev._clean_key("other", "x") is None


class FakeSession:
    """Enough of a session for `evolve` when the store calls are monkeypatched."""


def test_evolve_maps_proposes_and_skips(monkeypatch) -> None:
    by_key = {
        "other:default_payment_terms_days": [
            row("other:default_payment_terms_days", "Default payment term is 60 days.")
        ],
        "other:credit_note_link": [
            row("other:credit_note_link", "Credit notes quote the original invoice.", "text", None)
        ],
        "other:document_version": [
            row("other:document_version", "This is version 4.0.", "text", None)
        ],
    }
    saved = {}
    monkeypatch.setattr(ev, "collect", lambda s: by_key)
    monkeypatch.setattr(ev.kb, "save_schema", lambda s, o, mode: saved.setdefault("v", 2))
    monkeypatch.setattr(
        ev.kb, "add_review_item", lambda s, kind, payload: saved.update(item=payload)
    )

    def fake_llm(prompt, schema, **kw):
        if schema is ev._Pick:
            return schema(choice=0, reason="none")
        groups = [ln for ln in prompt.splitlines() if ln.startswith("Group ")]
        answers = []
        for ln in groups:
            n = int(ln.split()[1].rstrip(":"))
            if "credit_note" in ln:
                answers.append(
                    ev._NewAttribute(
                        group=n,
                        keep=True,
                        topic="credit_notes",
                        topic_label="Credit notes",
                        parameter="must_quote_original_invoice",
                        value_type="text",
                    )
                )
            else:
                answers.append(ev._NewAttribute(group=n, keep=False))
        return schema(attributes=answers)

    new, rep = ev.evolve(FakeSession(), ONTO, 1, "induced", fake_llm, fake_embed)
    actions = {d.keys[0]: (d.action, d.attribute) for d in rep.decisions}
    assert actions["other:default_payment_terms_days"] == ("map", "payments.default_term_days")
    assert actions["other:credit_note_link"] == ("new", "credit_notes.must_quote_original_invoice")
    assert actions["other:document_version"][0] == "skip"
    assert new is not None and new.topic("credit_notes") is not None
    assert new.attribute("credit_notes.must_quote_original_invoice") is not None
    assert rep.to_version == 2 and saved["item"]["remaps"] == rep.remaps()
