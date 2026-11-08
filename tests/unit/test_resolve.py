"""Authority resolution on hand-built assertions that mirror the corpus (TEST_PLAN level 3)."""

from __future__ import annotations

from datetime import date
from itertools import count

from app.graph.compare import LLMComparator, compare_values, deterministic
from app.graph.resolve import Assertion, resolve, resolve_group

_ids = count()

# label, status, rank, dated, valid_until
SOURCES = {
    "sop4": ("SOP v4.0", "current", 2, date(2026, 4, 1), None),
    "sop31": ("SOP v3.1", "superseded", 2, date(2023, 7, 1), date(2026, 3, 31)),
    "faq": ("FAQ", "stale", 6, date(2023, 10, 9), None),
    "video1": ("Video 1", "current", 4, date(2026, 2, 1), None),
    "memo": ("CM-X-02", "current", 1, date(2026, 4, 15), date(2027, 3, 31)),
    "interview": ("Interview 1", "record", 5, date(2026, 9, 8), None),
    "faq_new": ("FAQ 2027", "current", 6, date(2027, 1, 1), None),
}


def mk(
    src: str,
    number=None,
    text="",
    vtype="percentage",
    client="all",
    kind="rule",
    attribute="price_tolerance.pct_of_line",
    items=None,
) -> Assertion:
    label, status, rank, dated, until = SOURCES[src]
    return Assertion(
        key=f"k{next(_ids)}",
        subject_id="topic-1",
        attribute=attribute,
        client=client,
        value={
            "type": vtype,
            "number": number,
            "unit": "%" if vtype == "percentage" else None,
            "text": text or str(number),
            "items": items,
        },
        kind=kind,
        statement=f"{attribute} = {text or number}",
        source_id=src,
        source_label=label,
        source_status=status,
        authority_rank=rank,
        asserted_from=dated,
        asserted_to=until,
    )


def test_current_sop_beats_old_sop_and_faq_and_video_corroborates() -> None:
    v4, v31, faq, video = mk("sop4", 1), mk("sop31", 2), mk("faq", 2), mk("video1", 1)
    conflicts = resolve_group([v31, faq, v4, video], deterministic)
    assert v4.status == "current" and v4.valid_from == date(2026, 4, 1) and v4.valid_to is None
    assert v31.status == "superseded" and v31.valid_to == date(2026, 4, 1)  # last day 31 Mar
    assert faq.status == "superseded" and faq.valid_to == date(2026, 4, 1)
    assert video.status == "corroborating"
    assert v4.supersedes_key in (v31.key, faq.key)
    assert conflicts == []  # the losers' sources are not current


def test_client_memo_overrides_for_its_client_only_and_expires() -> None:
    general, memo = (
        mk("sop4", 0, attribute="qty.pct"),
        mk("memo", 5, client="Northwind", attribute="qty.pct"),
    )
    resolve_group([general, memo], deterministic)
    assert general.status == "current" and general.client == "all"
    assert memo.status == "current" and memo.valid_to == date(2027, 4, 1)


def test_authority_beats_recency() -> None:
    sop, newer = mk("sop4", 1), mk("faq_new", 2)  # newer but lower-ranked
    conflicts = resolve_group([sop, newer], deterministic)
    assert sop.status == "current"
    assert newer.status == "overridden" and newer.valid_from == newer.valid_to  # never in force
    assert [c.kind for c in conflicts] == ["value"]  # both current: the owner should know


def test_practice_never_overrides_and_flags_contradiction() -> None:
    rule, tip = mk("sop4", 1), mk("interview", 2, kind="practice")
    conflicts = resolve_group([rule, tip], deterministic)
    assert rule.status == "current" and tip.status == "current"
    assert [c.kind for c in conflicts] == ["practice_vs_rule"]
    same_tip = mk("interview", 1, kind="practice")
    assert resolve_group([mk("sop4", 1), same_tip], deterministic) == []


def test_no_current_source_is_pending_and_superseded_only_expires() -> None:
    stale = mk("faq", 3, attribute="other:faq_only")
    resolve_group([stale], deterministic)
    assert stale.status == "pending"
    old = mk("sop31", 2, attribute="other:old_only")
    resolve_group([old], deterministic)
    assert old.status == "superseded" and old.valid_to == date(2026, 4, 1)


def test_unknown_wording_from_current_source_corroborates() -> None:
    a = mk("sop4", text="Raise QA_RELEASE_PENDING and hold", vtype="text", attribute="qa.action")
    b = mk("video1", text="Hold until QA releases the batch", vtype="text", attribute="qa.action")
    resolve_group([a, b], deterministic)
    assert a.status == "current" and b.status == "corroborating"


def test_groups_are_independent() -> None:
    a = mk("sop4", 1)
    b = mk("sop31", 2, attribute="price_tolerance.cap")
    resolve([a, b], deterministic)
    assert a.status == "current" and b.status == "superseded"


def test_compare_values() -> None:
    p = {"type": "percentage", "unit": "%"}
    assert compare_values({**p, "number": 1}, {**p, "number": 1.0}) == "same"
    assert compare_values({**p, "number": 1}, {**p, "number": 2}) == "different"
    assert (
        compare_values(
            {"type": "days", "number": 2, "unit": "days"},
            {"type": "days", "number": 2, "unit": "working_days"},
        )
        == "unknown"
    )
    assert (
        compare_values(
            {"type": "list", "items": ["Cement", "sand"]},
            {"type": "list", "items": ["cement", "Sands"]},
        )
        == "same"
    )
    assert (
        compare_values(
            {"type": "text", "text": "Lower of 1% and 500."},
            {"type": "text", "text": "lower of 1 % and 500"},
        )
        == "same"
    )


def test_failed_llm_comparison_is_unknown_not_fatal() -> None:
    def boom(*a, **k):
        raise RuntimeError("timeout")

    cmp = LLMComparator(boom)
    a = mk("sop4", text="x", vtype="text")
    b = mk("faq", text="y", vtype="text")
    assert cmp(a, b) == "unknown" and cmp.failures


def test_complementary_values_from_one_source_are_one_list() -> None:
    attr = "payments.run_days"
    tue = mk("sop4", text="Tuesday", vtype="enum", attribute=attr)
    fri = mk("sop4", text="Friday", vtype="enum", attribute=attr)
    both = mk(
        "sop4", text="Tuesday and Friday", vtype="enum", attribute=attr, items=["Tuesday", "Friday"]
    )
    old = mk("sop31", text="Thursday", vtype="enum", attribute=attr)
    conflicts = resolve_group([tue, fri, both, old], deterministic)
    assert both.status == "current"
    assert tue.status == fri.status == "corroborating"
    assert old.status == "superseded" and conflicts == []
