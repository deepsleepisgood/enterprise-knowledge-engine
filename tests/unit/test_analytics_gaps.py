"""Analytics' "not answered" list: one row per question, dropped once it is dealt with."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.api.insights import open_gaps

T0 = datetime(2026, 11, 16, 8, 0, tzinfo=UTC)


def same(keys: list[str]) -> dict[str, str]:
    """Exact wording only (the real grouping embeds the questions)."""
    return {k: k for k in keys}


def ask(i: int, q: str, status: str, minutes: int) -> dict:
    return {
        "id": i,
        "question": q,
        "client": None,
        "status": status,
        "created_at": T0 + timedelta(minutes=minutes),
    }


def esc(q: str, status: str, minutes: int) -> SimpleNamespace:
    return SimpleNamespace(question=q, status=status, created_at=T0 + timedelta(minutes=minutes))


def test_repeats_show_once_with_a_count() -> None:
    rows = [  # newest first, as recent_answers returns them
        ask(3, "What is the canteen subsidy?", "unsupported", 3),
        ask(2, "what is the canteen subsidy", "unsupported", 2),
        ask(1, "What is the canteen subsidy? ", "unverified", 1),
    ]
    (gap,) = open_gaps(rows, [], same)
    assert gap["id"] == 3 and gap["times"] == 3


def test_a_question_answered_later_is_not_a_gap() -> None:
    rows = [
        ask(2, "Night canteen subsidy?", "answered", 5),
        ask(1, "Night canteen subsidy?", "unsupported", 1),
    ]
    assert open_gaps(rows, [], same) == []


def test_closed_or_resolved_escalation_removes_it_until_asked_again() -> None:
    rows = [ask(1, "Dress code?", "unsupported", 1), ask(0, "Parking?", "unsupported", 0)]
    escalations = [esc("Dress code?", "closed", 2), esc("Parking?", "open", 1)]
    assert [g["question"] for g in open_gaps(rows, escalations, same)] == ["Parking?"]
    # Asked again after the owner closed it, and still not answered: a gap again.
    again = [ask(5, "Dress code?", "unsupported", 10), *rows]
    assert "Dress code?" in [g["question"] for g in open_gaps(again, escalations, same)]


def test_rewordings_group_together_and_specialist_routes_are_not_gaps() -> None:
    rows = [
        ask(3, "Canteen subsidy for staff working the night shift?", "unsupported", 3),
        ask(2, "Canteen subsidy for night-shift staff?", "unsupported", 2),
        ask(1, "Which TDS section for a CCTV AMC?", "needs_specialist", 1),
    ]

    def reworded(keys: list[str]) -> dict[str, str]:
        return {k: ("canteen" if "canteen" in k else k) for k in keys}

    (gap,) = open_gaps(rows, [], reworded)
    assert gap["id"] == 3 and gap["times"] == 2


def test_real_grouping_merges_rewordings_but_not_other_questions() -> None:
    from app.api.insights import _embedding_groups

    keys = [
        "what is the canteen subsidy for night-shift staff",
        "what is the canteen subsidy for staff working the night shift",
        "what is the canteen subsidy per meal for staff at the hyderabad centre",
    ]
    g = _embedding_groups(keys)
    assert g[keys[0]] == g[keys[1]] != g[keys[2]]
