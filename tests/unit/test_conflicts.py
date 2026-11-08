"""Conflict scan helpers and the answer-key matcher (no database, no LLM)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

from app.graph.conflicts import quick_verdict, reason
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
