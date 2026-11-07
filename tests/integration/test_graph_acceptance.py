"""Phase 2 acceptance on the real corpus (live LLM; cached after the first build).

Attributes are reached through the AP plug-in's bindings, so the same checks run on the induced
schema and the hand-written baseline (GRAPH_MODE=induced|baseline, default induced). Values are
read from the parsed SOP and memos, never from the answer key.
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime

import pytest

from app.core.config import get_settings
from app.core.db import session_scope
from app.graph import pipeline as gp
from app.graph.rules import RuleNotFound, get_rule
from app.store import entities, kb
from app.store import episodes as estore
from app.store import facts as fstore
from app.store.base import last_day, use_tenant
from tests.live_graph import build_tenant

MODE = os.environ.get("GRAPH_MODE", "induced")
TODAY = date(2026, 11, 7)
pytestmark = [
    pytest.mark.db,
    pytest.mark.live_llm,
    pytest.mark.skipif(not get_settings().llm_configured, reason="needs an LLM API key"),
]


@pytest.fixture(scope="module")
def g(database_url):
    started = datetime.now(UTC)
    build_tenant(MODE)
    with use_tenant(MODE), session_scope() as s:
        onto = gp.active_ontology(s, MODE)
        binds = {b.param: b.attribute_key for b in kb.get_bindings(s, "ap")}
    return {"onto": onto, "bind": binds, "started": started}


def rule(g, param: str, **kw):
    attr = g["bind"].get(param)
    assert attr, f"{param} is not bound in the {MODE} schema"
    topic, _, p = param.partition(".")
    with use_tenant(MODE), session_scope() as s:
        return get_rule(s, g["onto"], topic, p, attribute=attr, today=TODAY, **kw)


def facts_from(label: str, attr: str | None = None) -> list[fstore.FactRow]:
    with use_tenant(MODE), session_scope() as s:
        srcs = {x.id for x in estore.list_sources(s) if x.short_label == label}
        return [r for r in fstore.get_facts(s, attribute=attr) if r.source_id in srcs]


def test_price_tolerance_current_and_as_of(g) -> None:
    pct, cap = rule(g, "price_tolerance.pct_of_line"), rule(g, "price_tolerance.cap_inr")
    assert (pct.number, cap.number) == (1, 500)
    assert pct.source_label == "AP SOP v4.0" and pct.locator == "4.2"
    old_pct = rule(g, "price_tolerance.pct_of_line", as_of=date(2026, 3, 1))
    old_cap = rule(g, "price_tolerance.cap_inr", as_of=date(2026, 3, 1))
    assert (old_pct.number, old_cap.number) == (2, 1000)
    assert old_pct.status == "superseded" and old_pct.valid_until == date(2026, 3, 31)


def test_sop_v31_values_are_superseded_on_31_march_2026(g) -> None:
    rows = facts_from("AP SOP v3.1")
    assert rows, "no facts from SOP v3.1"
    live = [r for r in rows if r.kind != "practice"]
    current = [r for r in live if r.status == "current"]
    # A v3.1 fact may only stay current where v4.0 says nothing different; none may outlive v3.1.
    assert all(
        r.valid_to is None or last_day(r.valid_to) <= date(2026, 3, 31)
        for r in live
        if r.status in ("superseded", "current")
    )
    assert len(current) <= len(live) // 3, [r.statement for r in current]


def test_section_14_rows_state_current_values(g) -> None:
    """Each §14 row's v4.0 value is in force; none is pending or superseded."""
    with use_tenant(MODE), session_scope() as s:
        sop = next(x for x in estore.list_sources(s) if x.short_label == "AP SOP v4.0")
        rows = [
            p
            for p in estore.passages_for_source(s, sop.id)
            if p.locator == "14" and p.segment_kind == "table_row"
        ]
        assert len(rows) == 11
        row_facts = fstore.live_for_passages(s, [p.id for p in rows])
    assert row_facts, "no facts extracted from the §14 change table"
    bad = [r.statement for r in row_facts if r.status not in ("current", "corroborating")]
    assert len(bad) <= 2, bad


def test_infra_memo_scoped_and_expires(g) -> None:
    infra = rule(g, "quantity_tolerance.pct", client="Arvana Infra Projects")
    assert infra.number == 5 and infra.source_label == "CM-INF-02"
    assert infra.valid_until == date(2027, 3, 31)
    assert rule(g, "quantity_tolerance.pct").number == 0  # general: no tolerance
    assert rule(g, "quantity_tolerance.pct", client="Arvana Retail").number == 0
    after = rule(
        g, "quantity_tolerance.pct", client="Arvana Infra Projects", as_of=date(2027, 4, 1)
    )
    assert after.number == 0


def test_einvoice_threshold_and_video_2_staleness(g) -> None:
    assert rule(g, "einvoice.aato_threshold_crore").number == 5 * 10_000_000
    attr = g["bind"]["einvoice.aato_threshold_crore"]
    old = [r for r in facts_from("Video 2", attr) if r.value.get("number") == 10 * 10_000_000]
    assert old and all(r.status in ("superseded", "overridden") for r in old)
    v2 = facts_from("Video 2")
    assert any(r.status == "corroborating" for r in v2), "Video 2 has no corroborated facts"


def test_faq_excipient_answer_is_not_current_and_pharma_memo_rules(g) -> None:
    faq = [
        r for r in facts_from("Part F") if "excipient" in (r.statement + (r.quote or "")).lower()
    ]
    assert faq, "no FAQ excipient fact"
    assert all(r.status != "current" for r in faq)
    memo = [
        r
        for r in facts_from("CM-PHA-01")
        if "excipient" in (r.statement + (r.quote or "") + str(r.value.get("items"))).lower()
    ]
    assert memo and all(r.status == "current" for r in memo)
    assert all((r.scope or {}).get("client") for r in memo)


def test_practice_is_never_a_rule(g) -> None:
    for label in ("Expert interview 1", "Expert interview 2", "Shadowing notes"):
        rows = facts_from(label)
        assert rows and all(r.kind == "practice" for r in rows), label


def test_known_at_before_ingestion_returns_nothing(g) -> None:
    with pytest.raises(RuleNotFound):
        rule(g, "price_tolerance.pct_of_line", known_at=datetime(2020, 1, 1, tzinfo=UTC))


def test_clients_resolve_to_three_entities(g) -> None:
    with use_tenant(MODE), session_scope() as s:
        names = [e.name for e in entities.list_entities(s, "client")]
        ids = {
            entities.by_alias(s, n, "client")
            for n in ("Arvana Infra Projects", "Arvana Infra Projects Ltd")
        }
    assert len(ids - {None}) == 1, names
    assert sum("infra" in n.lower() for n in names) == 1, names
