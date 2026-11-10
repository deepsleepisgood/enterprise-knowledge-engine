"""Conflict scan helpers and the answer-key matcher (no database, no LLM)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

from app.graph.conflicts import _authoritative, comparable, quick_verdict, reason
from app.store.facts import FactRow
from evaluation.conflict_key import Detected, match, places, score


def fact(fid: int, value: dict, source: str = "s1", **kw) -> FactRow:
    base = {
        "id": fid,
        "origin_key": f"o{fid}",
        "subject_id": "e1",
        "attribute": "price_tolerance.general_percentage",
        "value": value,
        "scope": {},
        "statement": "stmt",
        "kind": "rule",
        "status": "current",
        "valid_from": datetime(2026, 4, 1, tzinfo=UTC),
        "valid_to": None,
        "recorded_at": datetime(2026, 11, 1, tzinfo=UTC),
        "retracted_at": None,
        "authority_rank": 1,
        "source_id": source,
        "source_label": "Doc v4",
        "locator": "4.2",
    }
    return FactRow(**{**base, **kw})


def test_quick_verdict_settles_numbers_and_lists_only() -> None:
    one = {"type": "percentage", "number": 1, "unit": "%"}
    two = {"type": "percentage", "number": 2, "unit": "%"}
    assert quick_verdict(fact(1, one), fact(2, two)) == "different"
    assert quick_verdict(fact(1, one), fact(2, dict(one))) == "same"
    both = {"type": "list", "items": ["Tuesday", "Friday"]}
    assert quick_verdict(fact(1, both), fact(2, {"type": "enum", "text": "Tuesday"})) == "narrower"
    # differently worded text is for the judge, never "different" by string comparison
    a = {"type": "enum", "text": "raise it to the Tax Desk"}
    b = {"type": "enum", "text": "send it to Tax Desk"}
    assert quick_verdict(fact(1, a), fact(2, b)) is None


def test_reason_names_precedence_and_dates() -> None:
    new = SimpleNamespace(
        id="s1",
        status="current",
        dated=date(2026, 4, 1),
        supersedes_source_id="s0",
        short_label="Doc v4",
    )
    old = SimpleNamespace(
        id="s0",
        status="superseded",
        dated=date(2023, 1, 1),
        supersedes_source_id=None,
        short_label="Doc v3",
    )
    a = fact(1, {"type": "number", "number": 1}, "s1")
    b = fact(2, {"type": "number", "number": 2}, "s0", source_label="Doc v3", locator="3")
    why = reason(a, b, "value", {"s1": new, "s0": old})
    assert "replaced" in why and "01 Apr 2026" in why and "01 Jan 2023" in why


def test_key_places_and_matching() -> None:
    ps = places("A_v4.docx §4.2 and M.docx Part C (CM-X-01): 5%")
    assert [(p.file, p.section) for p in ps] == []  # file names must look like the corpus's
    ps = places("PS-07_A.docx §3, PS-07_B.docx Video 2 [03:40], PS-07_C.docx Part F: x")
    assert [(p.file, p.section) for p in ps] == [
        ("PS-07_A.docx", "3"),
        ("PS-07_B.docx", "video 2"),
        ("PS-07_C.docx", "part f"),
    ]
    from evaluation.conflict_key import Known

    key = [
        Known(
            "K1",
            "Payment runs",
            places("PS-07_N.docx §9: x"),
            places("PS-07_O.docx §8: y"),
            "SOP v4.0",
        ),
        Known(
            "K2",
            "MSME payment term",
            places("PS-07_N.docx §9: x"),
            places("PS-07_O.docx §8: y"),
            "SOP v4.0",
        ),
    ]
    d = Detected(
        "PS-07_N.docx",
        "9",
        "PS-07_O.docx",
        "8",
        "AP SOP v4.0",
        "value",
        "msme supplier payment term 45 days 60 days",
    )
    assert match(d, key).id == "K2"
    wrong = Detected(
        "PS-07_N.docx", "9", "PS-07_O.docx", "8", "AP SOP v4.0", "value", "unrelated words"
    )
    assert match(wrong, key) is None
    sc = score([d], key)
    assert sc["recall"] == 1 and sc["authoritative_right"] == ["K2"]


def test_tie_on_topic_words_is_broken_by_stated_values() -> None:
    from evaluation.conflict_key import Known

    key = [
        Known(
            "K1",
            "Payment runs",
            places("PS-07_N.docx §9: x"),
            places("PS-07_O.docx §8: y"),
            "SOP v4.0",
            detail="Tuesday and Friday Thursday",
        ),
        Known(
            "K2",
            "MSME payment term",
            places("PS-07_N.docx §9: x"),
            places("PS-07_O.docx §8: y"),
            "SOP v4.0",
            detail="45 days 15 days 60 days",
        ),
    ]
    # "payment" and "run" tie K1 (2 words) with K2 ("payment", "msme"); the values decide
    d = Detected(
        "PS-07_N.docx",
        "9",
        "PS-07_O.docx",
        "8",
        "AP SOP v4.0",
        "value",
        "payment_run_schedule.msme_max_days 45 day 60 days",
    )
    assert match(d, key).id == "K2"


def test_unit_only_for_numbers() -> None:
    from app.graph.conflicts import _unit

    assert _unit(fact(1, {"type": "percentage", "number": 5, "unit": "%"})) == "%"
    assert _unit(fact(1, {"type": "days", "number": 45, "unit": "days"})) == "day"
    assert _unit(fact(1, {"type": "enum", "text": "Friday"})) is None


def test_rule_side_is_never_an_outdated_source() -> None:
    old = fact(1, {"type": "enum", "text": "Controller"}, source="v3", status="corroborating")
    new = fact(2, {"type": "enum", "text": "Controller"}, source="v4", status="corroborating")
    outdated = lambda f: f.source_id == "v3"  # noqa: E731 (v3 is a superseded version)
    assert _authoritative([old, new], outdated).id == 2
    assert _authoritative([old], outdated) is None
    tip = fact(
        3, {"type": "enum", "text": "Manager"}, source="notes", kind="practice", authority_rank=7
    )
    assert not comparable(old, tip, "group", outdated)
    assert comparable(new, tip, "group", outdated)


def test_practice_from_an_equally_ranked_document_is_not_practice_vs_rule() -> None:
    rule = fact(1, {"type": "enum", "text": "Controller"}, source="sop", authority_rank=1)
    table = fact(
        2, {"type": "enum", "text": "Lead"}, source="sop", kind="practice", authority_rank=1
    )
    habit = fact(
        3, {"type": "enum", "text": "Lead"}, source="interview", kind="practice", authority_rank=6
    )
    never = lambda f: False  # noqa: E731
    assert not comparable(rule, table, "group", never)
    assert comparable(rule, habit, "group", never)


def test_bare_yes_no_neighbour_is_not_compared_with_a_value() -> None:
    rule = fact(1, {"type": "enum", "text": "AP Controller"})
    flag = fact(2, {"type": "boolean", "text": "true"}, source="s2", attribute="x.approves")
    never = lambda f: False  # noqa: E731
    assert not comparable(rule, flag, "neighbour", never)
    assert comparable(rule, flag, "group", never)  # same attribute: the judge still decides
    yes = fact(3, {"type": "boolean", "text": "true"})
    assert comparable(
        yes, fact(4, {"type": "boolean", "text": "false"}, source="s2"), "neighbour", never
    )
