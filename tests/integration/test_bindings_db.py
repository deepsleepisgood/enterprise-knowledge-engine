"""Phase 3 core: plug-in bindings and calculator dispatch against the database (fake LLM)."""

from __future__ import annotations

from datetime import date

import pytest

from app.core.db import session_scope
from app.graph.ontology import Attribute, Ontology, Topic
from app.graph.rules import RuleNotFound
from app.plugins import registry
from app.plugins.bindings import BoundRules, bind
from app.plugins.calculate import calculate, families
from app.store import entities, kb
from app.store import facts as fstore
from app.store.base import day_start

pytestmark = pytest.mark.db

# An induced schema whose names differ from the plug-in's parameters.
ONTO = Ontology(
    topics=[Topic(key="price_variance", label="Price variance", synonyms=["price tolerance"])],
    attributes=[
        Attribute(
            key="price_variance.share_of_line_value",
            topic="price_variance",
            label="share of PO line value",
            value_type="percentage",
            description="percentage of the PO line value an invoice price may exceed",
        ),
        Attribute(
            key="price_variance.absolute_cap",
            topic="price_variance",
            label="absolute cap per line",
            value_type="money",
            description="cap in rupees on the price excess per line",
        ),
    ],
)


def fake_pick(prompt, schema, **kw):
    """Pick the candidate whose key matches the parameter's meaning."""
    lines = [ln for ln in prompt.splitlines() if ln[:2].rstrip(".").isdigit()]
    need = prompt.split("Candidate attributes", 1)[0]
    want = (
        "share_of_line"
        if "line value that an invoice unit price" in need
        else ("absolute_cap" if "cap in rupees on the price excess" in need else "zzz")
    )
    for ln in lines:
        if want in ln:
            return schema.model_validate({"choice": int(ln.split(".")[0]), "reason": "match"})
    return schema.model_validate({"choice": 0, "reason": "none"})


def _fact(s, attr: str, number: float, unit: str) -> None:
    topic = entities.create(s, "topic", "Price variance")
    fstore.insert(
        s,
        fstore.NewFact(
            origin_key=attr,
            subject_id=topic,
            attribute=attr,
            value={
                "type": "percentage" if unit == "%" else "money",
                "number": number,
                "unit": unit,
                "text": str(number),
            },
            statement=f"{attr} {number}",
            kind="rule",
            status="current",
            valid_from=day_start(date(2026, 4, 1)),
        ),
    )


def test_bind_maps_params_and_calculator_reads_bound_facts(db) -> None:
    plugin = registry.get("ap")
    assert plugin is not None and "price" in families("ap")
    with session_scope() as s:
        _fact(s, "price_variance.share_of_line_value", 1, "%")
        _fact(s, "price_variance.absolute_cap", 500, "INR")
        results = {r.param: r for r in bind(s, plugin, ONTO, structured_fn=fake_pick)}
    assert results["price_tolerance.pct_of_line"].attribute == "price_variance.share_of_line_value"
    assert results["price_tolerance.cap_inr"].attribute == "price_variance.absolute_cap"
    assert results["tds.no_pan_rate"].attribute is None  # nothing in this schema holds it
    with session_scope() as s:
        res = calculate(
            s,
            ONTO,
            "ap",
            "price",
            {"po_unit_price": 400, "invoice_unit_price": 395, "quantity": 500},
            today=date(2026, 11, 7),
        )
        assert res.passed is True
        res = calculate(
            s,
            ONTO,
            "ap",
            "price",
            {"po_unit_price": 395, "invoice_unit_price": 400, "quantity": 500},
            today=date(2026, 11, 7),
        )
        assert res.passed is False and res.result["limit"] == 500 and res.exception_code
        with pytest.raises(RuleNotFound, match="not bound"):
            BoundRules(s, ONTO, "ap").get("tds", "no_pan_rate")


def test_owner_confirmed_binding_is_kept(db) -> None:
    plugin = registry.get("ap")
    with session_scope() as s:
        kb.put_binding(
            s,
            "ap",
            "price_tolerance.cap_inr",
            attribute_key="price_variance.absolute_cap",
            confidence=1.0,
            confirmed_by="owner",
            meta={},
        )
        out = {
            r.param: r
            for r in bind(
                s,
                plugin,
                ONTO,
                structured_fn=lambda *a, **k: (
                    (_ for _ in ()).throw(AssertionError("no LLM call expected for this param"))
                    if "price_tolerance cap_inr" in a[0].split("Candidate", 1)[0]
                    else fake_pick(*a, **k)
                ),
            )
        }
    assert out["price_tolerance.cap_inr"].method == "owner"


def test_exact_key_binding_needs_no_llm(db) -> None:
    base = Ontology.model_validate(registry.baseline_schema())
    with session_scope() as s:
        out = bind(s, registry.get("ap"), base, structured_fn=None)
    assert all(r.attribute == r.param and r.method == "exact key" for r in out)
