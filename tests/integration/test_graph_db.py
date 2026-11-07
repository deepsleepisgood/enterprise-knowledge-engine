"""Persistence and the rules API against Postgres, using hand-built claims (no LLM).

Mirrors the corpus: SOP v4.0 vs v3.1 vs the FAQ on price tolerance, and the general
"no quantity tolerance" rule vs the Infra memo (which expires 31 Mar 2027).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select, text

from app.core.config import get_settings
from app.core.models import Claim, Conflict, KbVersion
from app.graph.resolve import resolve
from app.graph.rules import RuleNotFound, expert_tips, get_rule, older_claims
from app.graph.schema import ClaimRec
from app.graph.store import load_passages, persist

pytestmark = pytest.mark.db
TODAY = date(2026, 11, 7)


def _rec(
    pack,
    key,
    source_id,
    topic,
    parameter,
    number,
    *,
    vtype="percentage",
    unit="%",
    client=None,
    passage_id=None,
) -> ClaimRec:
    src = pack.sources[source_id]
    return ClaimRec(
        key=key,
        topic=topic,
        parameter=parameter,
        client=client or src.client_scope,
        value={"type": vtype, "number": number, "unit": unit, "text": str(number)},
        kind="practice" if src.kind in ("interview", "shadowing") else "rule",
        statement=f"{topic}.{parameter} = {number}",
        source_id=source_id,
        source_kind=src.kind,
        source_status=src.status,
        authority_rank=src.authority_rank,
        valid_at=src.dated,
        source_valid_to=src.valid_to,
        passage_id=passage_id,
        scope={"client": client or src.client_scope},
        meta={"origin": "corpus"},
    )


@pytest.fixture(scope="module")
def graph(database_url, pack):
    from app.core.db import session_scope
    from app.ingest.loader import ingest

    with session_scope() as s:
        ingest(s, pack, get_settings().data_dir, with_vendors=False)
        s.execute(text("TRUNCATE claims, conflicts, changes, kb_versions RESTART IDENTITY CASCADE"))
        pid = {(r.source_id, r.locator): r.id for r in load_passages(s)}

    def claims():
        return [
            _rec(
                pack,
                "t-v4-pct",
                "sop_v4",
                "price_tolerance",
                "pct_of_line",
                1,
                passage_id=pid[("sop_v4", "4.2")],
            ),
            _rec(
                pack,
                "t-v4-cap",
                "sop_v4",
                "price_tolerance",
                "cap_inr",
                500,
                vtype="money",
                unit="INR",
                passage_id=pid[("sop_v4", "4.2")],
            ),
            _rec(
                pack,
                "t-v3-pct",
                "sop_v3_1",
                "price_tolerance",
                "pct_of_line",
                2,
                passage_id=pid[("sop_v3_1", "3")],
            ),
            _rec(pack, "t-faq-pct", "faq_2023", "price_tolerance", "pct_of_line", 2),
            _rec(
                pack,
                "t-sop-qty",
                "sop_v4",
                "quantity_tolerance",
                "pct",
                0,
                passage_id=pid[("sop_v4", "4.3")],
            ),
            _rec(
                pack,
                "t-memo-qty",
                "cm_inf_02",
                "quantity_tolerance",
                "pct",
                5,
                passage_id=pid[("cm_inf_02", "Part C (CM-INF-02)")],
            ),
            _rec(
                pack,
                "t-tip",
                "shadowing",
                "price_tolerance",
                "pct_of_line",
                1,
                passage_id=pid[("shadowing", "Shadowing 12:15")],
            ),
        ]

    before = datetime.now(UTC) - timedelta(seconds=1)
    with session_scope() as s:
        first = persist(s, resolve(claims()))
    return {"claims": claims, "first": first, "before": before}


def _s():
    from app.core.db import session_scope

    return session_scope()


def test_first_persist_inserts_and_bumps_version(graph) -> None:
    first = graph["first"]
    assert first.inserted == 7 and first.kb_version == 1
    with _s() as s:
        assert s.scalar(select(func.count()).select_from(KbVersion)) == 1


def test_current_rule_and_citation(graph) -> None:
    with _s() as s:
        pct = get_rule(s, "price_tolerance", "pct_of_line", today=TODAY)
        cap = get_rule(s, "price_tolerance", "cap_inr", today=TODAY)
    assert pct.number == 1 and pct.source_id == "sop_v4" and pct.citation == "SOP v4.0 §4.2"
    assert cap.number == 500


def test_superseded_rows_kept_with_dates(graph) -> None:
    with _s() as s:
        v3 = s.scalar(select(Claim).where(Claim.origin_key == "t-v3-pct"))
        v4 = s.scalar(select(Claim).where(Claim.origin_key == "t-v4-pct"))
        assert v3.status == "superseded" and v3.invalid_at == date(2026, 3, 31)
        assert v3.expired_at is not None
        assert v4.supersedes_id is not None
        older = older_claims(s, "price_tolerance")
    assert {o.source_id for o in older} == {"sop_v3_1", "faq_2023"}


def test_audit_query_returns_v3_1_before_v4(graph) -> None:
    with _s() as s:
        old = get_rule(s, "price_tolerance", "pct_of_line", as_of=date(2026, 3, 1))
    assert old.number == 2 and old.source_id == "sop_v3_1"  # SOP outranks the FAQ by kind


def test_client_memo_applies_to_its_client_and_expires(graph) -> None:
    with _s() as s:
        infra = get_rule(s, "quantity_tolerance", "pct", client="infra", today=TODAY)
        retail = get_rule(s, "quantity_tolerance", "pct", client="retail", today=TODAY)
        general = get_rule(s, "quantity_tolerance", "pct", today=TODAY)
        after = get_rule(s, "quantity_tolerance", "pct", client="infra", as_of=date(2027, 4, 1))
        today_after = get_rule(
            s, "quantity_tolerance", "pct", client="infra", today=date(2027, 4, 1)
        )
    assert infra.number == 5 and infra.source_id == "cm_inf_02"
    assert retail.number == 0 and general.number == 0
    assert after.number == 0 and after.source_id == "sop_v4"  # memo expired: no tolerance
    assert today_after.number == 0


def test_known_at_before_ingestion_returns_nothing(graph) -> None:
    with _s() as s, pytest.raises(RuleNotFound):
        get_rule(s, "price_tolerance", "pct_of_line", known_at=graph["before"], today=TODAY)


def test_missing_rule_raises_never_defaults(graph) -> None:
    with _s() as s, pytest.raises(RuleNotFound):
        get_rule(s, "price_tolerance", "no_such_parameter", today=TODAY)


def test_practice_is_a_tip_not_a_rule(graph) -> None:
    with _s() as s:
        tips = expert_tips(s, "price_tolerance")
        rule = get_rule(s, "price_tolerance", "pct_of_line", today=TODAY)
    assert [t.source_id for t in tips] == ["shadowing"]
    assert rule.source_id == "sop_v4"


def test_rebuild_is_idempotent(graph) -> None:
    with _s() as s:
        again = persist(s, resolve(graph["claims"]()))
        total = s.scalar(select(func.count()).select_from(Claim))
    assert (again.inserted, again.updated, again.retired) == (0, 0, 0)
    assert again.unchanged == 7 and again.kb_version == 1 and total == 7


def test_claims_missing_from_a_rebuild_are_retired_not_deleted(graph) -> None:
    keep = [c for c in graph["claims"]() if c.key != "t-faq-pct"]
    with _s() as s:
        rep = persist(s, resolve(keep))
        faq = s.scalar(select(Claim).where(Claim.origin_key == "t-faq-pct"))
        total = s.scalar(select(func.count()).select_from(Claim))
    assert rep.retired == 1 and rep.kb_version == 2
    assert total == 7 and faq.meta["retired"] is True and faq.expired_at is not None
    with _s() as s:  # restore for other tests
        persist(s, resolve(graph["claims"]()))


def test_conflicts_are_unique(graph, pack) -> None:
    extra = _rec(pack, "t-di-pct", "di_03", "price_tolerance", "pct_of_line", 2)
    with _s() as s:
        first = persist(s, resolve([*graph["claims"](), extra]))
        second = persist(s, resolve([*graph["claims"](), extra]))
        n = s.scalar(select(func.count()).select_from(Conflict))
    assert first.conflicts == 1 and second.conflicts == 0 and n == 1
