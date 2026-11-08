"""Phase 4 acceptance: T1-T8 and the as-of probe through ask() on the real graph (live LLM).

TEST_PLAN level 4. Runs in-process for now; Phase 7 points the same assertions at the API.
The questions are written from the brief's acceptance table, not copied from the answer key.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from app.core.config import get_settings
from tests.live_graph import build_tenant

pytestmark = [
    pytest.mark.db,
    pytest.mark.live_llm,
    pytest.mark.skipif(not get_settings().llm_configured, reason="needs an LLM API key"),
]
TODAY = date(2026, 11, 7)
MODE = "induced"


@pytest.fixture(scope="module")
def asker(database_url):
    build_tenant(MODE)
    from app.answer.pipeline import ask
    from app.store.base import use_tenant

    def run(question: str, **kw) -> dict:
        with use_tenant(MODE):
            return ask(question, today=TODAY, viewer="eval", **kw)

    return run


def _all_text(card: dict) -> str:
    parts = [card["rule"]["text"], card.get("decision") or "", card.get("exception_code") or ""]
    parts += [f"{w['label']} {w['value']}" for w in card.get("working") or []]
    return " ".join(parts)


def _why(card: dict) -> str:
    return json.dumps(
        {k: card.get(k) for k in ("status", "route", "rule", "working", "diagnostics")},
        ensure_ascii=False,
        default=str,
    )[:3000]


def test_t1_price_tolerance(asker) -> None:
    card = asker(
        "What is the price tolerance for an invoice line where the unit price is higher than "
        "the PO price?"
    )
    text = card["rule"]["text"]
    assert card["status"] in ("answered", "provisional"), _why(card)
    assert "1%" in text and "500" in text, _why(card)
    assert "2%" not in text and "1,000" not in text, _why(card)
    assert any("4.0" in c["short_label"] or "4.0" in c["file"] for c in card["rule"]["citations"])
    older = json.dumps(card["older_sources"], ensure_ascii=False)
    assert "3.1" in older, _why(card)


def test_t1_as_of_1_march_2026_returns_v31(asker) -> None:
    card = asker(
        "What is the price tolerance for an invoice line where the unit price is higher than "
        "the PO price?",
        as_of=date(2026, 3, 1),
    )
    text = card["rule"]["text"]
    assert card["as_of"] == "2026-03-01"
    assert "2%" in text and "1,000" in text, _why(card)
    assert any("3.1" in c["short_label"] or "3.1" in c["file"] for c in card["rule"]["citations"])


def test_t2_einvoice_above_threshold(asker) -> None:
    card = asker(
        "A supplier whose highest aggregate annual turnover since 2017-18 is ₹8.9 crore sends "
        "an invoice without an IRN. Can we accept it?"
    )
    allt = _all_text(card)
    assert card["exception_code"] == "IRN_MISSING", _why(card)
    assert "5 crore" in allt or "50,000,000" in allt, _why(card)
    assert "10 crore" not in card["rule"]["text"], _why(card)


def test_t3_pharma_excipients(asker) -> None:
    card = asker("Do Arvana Pharma excipient invoices need QA release before payment?")
    assert card["status"] in ("answered", "provisional", "needs_specialist"), _why(card)
    labels = " ".join(c["short_label"] for c in card["rule"]["citations"])
    assert "PHA" in labels, _why(card)
    assert "yes" in card["rule"]["text"].lower(), _why(card)
    flagged = json.dumps(card["older_sources"], ensure_ascii=False) + card["rule"]["text"]
    assert "FAQ" in flagged or "Part F" in flagged, _why(card)


def test_t4_infra_saturday_no_grn(asker) -> None:
    card = asker(
        "An Infra goods invoice arrived on Saturday with no GRN. Should I chase the site on "
        "Monday morning?"
    )
    labels = " ".join(c["short_label"] for c in card["rule"]["citations"])
    assert "4.6" in labels or "two working days" in card["rule"]["text"].lower(), _why(card)
    tip = card["expert_tip"] or {}
    practice = f"{tip.get('text', '')} {card['rule']['text']}".lower()
    assert "tuesday" in practice, _why(card)
    cited = labels + " " + str((tip.get("citation") or {}).get("short_label", ""))
    assert "interview 1" in cited.lower(), _why(card)  # label wording varies by build


def test_t5_price_calculation(asker) -> None:
    card = asker(
        "PO unit price ₹395 for 500 units; the invoice charges ₹400 per unit. Can the line "
        "pass the price match?"
    )
    allt = _all_text(card)
    assert card["exception_code"] == "PRICE_VAR", _why(card)
    assert "2,500" in allt and "1,975" in allt, _why(card)


def test_t6_tds_software_support(asker) -> None:
    card = asker(
        "We received a software support (AMC) invoice from a company for ₹4,80,000 excluding "
        "GST. How much TDS do we deduct?"
    )
    allt = _all_text(card)
    assert "194J" in allt and "9,600" in allt, _why(card)


def test_t7_msme_due_date(asker) -> None:
    card = asker(
        "A micro enterprise supplier registered on Udyam; invoice accepted on 01 August 2026; "
        "no written agreement on payment terms. What is the due date and which payment run "
        "should pay it?"
    )
    allt = _all_text(card)
    assert "16 Aug" in allt or "2026-08-16" in allt, _why(card)
    assert "14 Aug" in allt or "2026-08-14" in allt, _why(card)


def test_t8_canteen_subsidy_is_unsupported(asker) -> None:
    card = asker("What is the canteen subsidy for staff working the night shift?")
    assert card["status"] == "unsupported", _why(card)
    assert card["rule"]["text"] == "" and card["route_to"] and card["route_to"]["role"]
