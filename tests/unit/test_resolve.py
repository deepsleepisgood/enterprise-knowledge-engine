"""Authority resolution on hand-built claims that mirror the corpus (TEST_PLAN level 3)."""

from __future__ import annotations

from datetime import date
from itertools import count
from typing import Any

import pytest

from app.graph.compare import compare_values
from app.graph.resolve import resolve
from app.graph.schema import ClaimRec

_ids = count()


@pytest.fixture
def mk(pack):
    def _mk(
        source_id: str,
        topic: str,
        parameter: str,
        *,
        number: float | None = None,
        text: str = "",
        vtype: str = "percentage",
        unit: str | None = None,
        client: str | None = None,
        kind: str = "rule",
        items: list[str] | None = None,
    ) -> ClaimRec:
        src = pack.sources[source_id]
        if unit is None:
            unit = {"percentage": "%", "money": "INR"}.get(vtype)
        value: dict[str, Any] = {
            "type": vtype,
            "number": number,
            "unit": unit,
            "text": text or str(number),
            "items": items,
        }
        return ClaimRec(
            key=f"k{next(_ids)}",
            topic=topic,
            parameter=parameter,
            client=client or src.client_scope,
            value=value,
            kind="practice" if src.kind in ("interview", "shadowing") else kind,
            statement=f"{topic}.{parameter} = {text or number}",
            source_id=source_id,
            source_kind=src.kind,
            source_status=src.status,
            authority_rank=src.authority_rank,
            valid_at=src.dated,
            source_valid_to=src.valid_to,
            meta={"origin": "test"},
        )

    return _mk


def test_sop_v4_beats_v3_1_and_faq_video_corroborates(mk) -> None:
    v4 = mk("sop_v4", "price_tolerance", "pct_of_line", number=1)
    v3 = mk("sop_v3_1", "price_tolerance", "pct_of_line", number=2)
    faq = mk("faq_2023", "price_tolerance", "pct_of_line", number=2)
    video = mk("video_1", "price_tolerance", "pct_of_line", number=1)
    resolve([v3, faq, v4, video])
    assert v4.status == "current"
    assert v3.status == "superseded" and v3.invalid_at == date(2026, 3, 31)
    assert faq.status == "superseded" and faq.invalid_at == date(2026, 3, 31)
    assert video.status == "corroborating"
    assert v4.supersedes_key in {faq.key, v3.key}


def test_client_memo_overrides_for_its_client_only(mk) -> None:
    sop = mk("sop_v4", "quantity_tolerance", "pct", number=0, text="none")
    v3 = mk("sop_v3_1", "quantity_tolerance", "pct", number=2)
    memo = mk("cm_inf_02", "quantity_tolerance", "pct", number=5)
    faq = mk("faq_2023", "quantity_tolerance", "pct", number=10, client="infra")
    res = resolve([sop, v3, memo, faq])
    assert sop.status == "current" and sop.client == "all"
    assert memo.status == "current" and memo.client == "infra"
    assert memo.invalid_at == date(2027, 3, 31)  # memo expiry carried as invalid_at
    assert v3.status == "superseded"
    assert faq.status == "superseded" and faq.invalid_at == date(2026, 4, 14)
    assert not res.conflicts


def test_faq_excipients_superseded_by_pharma_memo(mk) -> None:
    memo = mk(
        "cm_pha_01",
        "qa_release",
        "materials",
        vtype="list",
        items=["active pharmaceutical ingredients", "excipients", "primary packaging"],
    )
    faq = mk(
        "faq_2023",
        "qa_release",
        "materials",
        vtype="list",
        client="pharma",
        items=["active pharmaceutical ingredients"],
    )
    resolve([memo, faq])
    assert memo.status == "current"
    assert faq.status == "superseded" and faq.invalid_at == date(2026, 1, 1)


def test_video_2_staleness_is_per_claim(mk) -> None:
    sop_pan = mk("sop_v4", "tds", "no_pan_rate", number=20)
    vid_pan = mk("video_2", "tds", "no_pan_rate", number=20)
    sop_irn = mk("sop_v4", "einvoice", "aato_threshold_crore", vtype="money", number=5e7)
    vid_irn = mk("video_2", "einvoice", "aato_threshold_crore", vtype="money", number=1e8)
    resolve([sop_pan, vid_pan, sop_irn, vid_irn])
    assert vid_pan.status == "corroborating"
    assert vid_irn.status == "superseded"


def test_practice_attaches_as_tip_and_never_overrides(mk) -> None:
    rule = mk(
        "sop_v4",
        "missing_grn",
        "action",
        vtype="text",
        text="hold as NO_GRN; reminder after two working days",
    )
    tip = mk(
        "interview_1",
        "missing_grn",
        "action",
        vtype="text",
        text="for Infra, wait until Tuesday noon before chasing",
    )
    res = resolve([rule, tip])
    assert rule.status == "current"
    assert tip.kind == "practice" and tip.status == "current"
    assert not res.conflicts  # wording differs; only a clear contradiction opens a conflict


def test_practice_contradicting_a_rule_opens_conflict(mk) -> None:
    rule = mk("sop_v4", "price_tolerance", "cap_inr", vtype="money", number=500)
    tip = mk("shadowing", "price_tolerance", "cap_inr", vtype="money", number=1000)
    res = resolve([rule, tip])
    assert rule.status == "current" and tip.status == "current"
    (conflict,) = res.conflicts
    assert conflict.kind == "practice_vs_rule" and conflict.authoritative_key == rule.key


def test_two_current_sources_disagreeing_open_value_conflict(mk) -> None:
    sop = mk("sop_v4", "price_tolerance", "pct_of_line", number=1)
    di = mk("di_03", "price_tolerance", "pct_of_line", number=2)
    res = resolve([sop, di])
    assert sop.status == "current" and di.status == "superseded"
    (conflict,) = res.conflicts
    assert conflict.kind == "value"
    assert di.invalid_at == di.valid_at  # started after the SOP: never valid


def test_stale_only_claim_is_pending_not_current(mk) -> None:
    faq = mk("faq_2023", "records", "retention_years", vtype="days", number=8, unit="years")
    resolve([faq])
    assert faq.status == "pending"


def test_stale_client_claim_settled_by_general_rule(mk) -> None:
    sop = mk("sop_v4", "rounding", "cap_inr", vtype="money", number=10)
    faq = mk("faq_2023", "rounding", "cap_inr", vtype="money", number=50, client="retail")
    resolve([sop, faq])
    assert faq.status == "superseded"


def test_compare_values() -> None:
    pct = {"type": "percentage", "unit": "%"}
    assert compare_values({**pct, "number": 1}, {**pct, "number": 1.0}) == "same"
    assert compare_values({**pct, "number": 1}, {**pct, "number": 2}) == "different"
    days = {"type": "days", "number": 2}
    assert compare_values({**days, "unit": "days"}, {**days, "unit": "working_days"}) == "unknown"
    lst = {"type": "list"}
    assert (
        compare_values({**lst, "items": ["Cement", "sand"]}, {**lst, "items": ["sand", "cement"]})
        == "same"
    )
    assert (
        compare_values({**lst, "items": ["api"]}, {**lst, "items": ["api", "excipient"]})
        == "unknown"
    )
    assert (
        compare_values(
            {"type": "text", "text": "Tuesday and Friday"},
            {"type": "text", "text": "tuesday  and friday."},
        )
        == "same"
    )


def test_subject_keeps_table_rows_apart(mk) -> None:
    a = mk("sop_v4", "exceptions", "owner", vtype="text", text="PO buyer")
    b = mk("sop_v4", "exceptions", "owner", vtype="text", text="Requester")
    a.scope["subject"], b.scope["subject"] = "PRICE_VAR", "QTY_VAR"
    resolve([a, b])
    assert a.status == b.status == "current"


def test_failed_llm_comparison_is_unknown_not_fatal(mk) -> None:
    from app.graph.compare import LLMComparator

    def boom(*args, **kwargs):
        raise RuntimeError("model unavailable")

    cmp = LLMComparator(structured_fn=boom)
    rule = mk("sop_v4", "missing_grn", "action", vtype="text", text="hold")
    old = mk("faq_2023", "missing_grn", "action", vtype="text", text="email the requester")
    resolve([rule, old], compare=cmp)
    assert old.status == "superseded" and cmp.failures
