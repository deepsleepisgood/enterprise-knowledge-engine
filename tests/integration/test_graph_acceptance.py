"""Phase 2 acceptance on the real corpus (BUILD_PLAN Phase 2, TEST_PLAN level 3).

Builds the graph in the test database with real extraction (MODEL_SMART) and the LLM
comparator. Results are cached on disk, so only the first run costs money (~$1).
The topics to check are read from SOP §14 as parsed, not from the answer key.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.models import Claim

pytestmark = [
    pytest.mark.db,
    pytest.mark.live_llm,
    pytest.mark.skipif(
        not get_settings().llm_configured,
        reason="needs an LLM API key (NVIDIA_API_KEY or ANTHROPIC_API_KEY) to extract claims",
    ),
]
TODAY = date(2026, 11, 7)

# §14 row label -> vocabulary topic (test-side mapping)
SECTION_14_TOPICS = {
    "Price tolerance": "price_tolerance",
    "Quantity tolerance": "quantity_tolerance",
    "Rounding": "rounding",
    "E-invoice threshold": "einvoice",
    "ITC check": "itc",
    "Bank changes": "bank_change",
    "Payment runs": "payments",
    "Approvals": "approvals",
    "Non-PO categories": "non_po",
    "MSME payment": "msme",
    "Duplicate check": "duplicate_check",
}


@pytest.fixture(scope="module")
def built(built_graph):
    return built_graph


def _claims(session, **where):
    q = select(Claim)
    for k, v in where.items():
        q = q.where(getattr(Claim, k) == v)
    return list(session.scalars(q))


def test_section_14_rows_map_to_known_topics(corpus) -> None:
    labels = {
        p.meta["row_label"]
        for p in corpus.passages
        if p.source_id == "sop_v4" and p.segment_kind == "table_row"
    }
    assert labels == set(SECTION_14_TOPICS)


@pytest.mark.parametrize(("label", "topic"), sorted(SECTION_14_TOPICS.items()))
def test_section_14_v4_current_v3_1_superseded(built, label, topic) -> None:
    from app.core.db import session_scope

    with session_scope() as s:
        v4 = [c for c in _claims(s, topic=topic, source_id="sop_v4") if c.kind != "practice"]
        v3 = _claims(s, topic=topic, source_id="sop_v3_1")
    assert any(c.status == "current" and c.scope.get("client") == "all" for c in v4), label
    assert not any(c.status == "current" for c in v3), f"{label}: a v3.1 claim is current"
    superseded = [c for c in v3 if c.status == "superseded"]
    assert superseded, f"{label}: no v3.1 claim was superseded"
    assert all(c.invalid_at == date(2026, 3, 31) for c in superseded)


def test_infra_memo_current_for_infra_only(built) -> None:
    from app.core.db import session_scope
    from app.graph.rules import get_rule

    with session_scope() as s:
        memo = _claims(s, source_id="cm_inf_02")
        infra = get_rule(s, "quantity_tolerance", "pct", client="infra", today=TODAY)
        retail = get_rule(s, "quantity_tolerance", "pct", client="retail", today=TODAY)
        expired = get_rule(s, "quantity_tolerance", "pct", client="infra", as_of=date(2027, 4, 1))
    assert memo and all(c.scope.get("client") == "infra" for c in memo)
    assert infra.source_id == "cm_inf_02" and infra.number == 5
    assert retail.source_id != "cm_inf_02" and retail.number == 0
    assert expired.source_id != "cm_inf_02"


def test_faq_excipient_claim_superseded_by_pharma_memo(built) -> None:
    from app.core.db import session_scope

    with session_scope() as s:
        faq = _claims(s, topic="qa_release", source_id="faq_2023")
        memo = _claims(s, topic="qa_release", source_id="cm_pha_01")
    assert any(c.status == "current" and c.scope.get("client") == "pharma" for c in memo)
    assert faq and all(c.status == "superseded" for c in faq)
