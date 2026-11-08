"""Evaluation harness pieces (no LLM, no database)."""

from __future__ import annotations

from collections import Counter

import pytest

from evaluation import dataset
from evaluation import scenario as sc
from evaluation.judge import cohen_kappa
from evaluation.metrics import citation_correct, norm_loc, outdated
from evaluation.run import grade_scenario_text

SOP = "PS-07_AP_SOP_v4.0_2026.docx"
PACK = "PS-07_desk_instructions_and_client_memos.docx"
TX = "PS-07_training_and_expert_transcripts.docx"


def card(*cites, text="", decision=None, working=None, older=None) -> dict:
    return {
        "rule": {"text": text, "citations": [dict(c) for c in cites]},
        "decision": decision,
        "working": working,
        "older_sources": older or [],
    }


def cite(file, locator, label=None):
    return {"file": file, "locator": locator, "short_label": label or locator}


def test_locator_normalisation_rules_from_the_test_plan() -> None:
    assert norm_loc("§4.2") == norm_loc("4.2") == "4.2"
    assert norm_loc("Part C (CM-INF-02)") == "part c"
    c = card(cite(SOP, "4.2", "AP SOP v4.0 §4.2"))
    assert citation_correct(c, SOP, "4.2", [])
    assert not citation_correct(c, SOP, "4.3", [])
    memo = card(cite(PACK, "Part C", "CM-INF-02 Part C"))
    assert citation_correct(memo, PACK, "Part C (CM-INF-02)", [])
    step = card(cite(PACK, "Part B, step 3", "DI-03 Part B, step 3"))
    assert citation_correct(step, PACK, "Part B, step 3", [])
    part = card(cite(PACK, "Part B", "DI-03 Part B"))
    assert not citation_correct(part, PACK, "Part B, step 3", [])
    assert citation_correct(part, PACK, "Part B, step 3", [], lenient=True)
    either = card(cite(SOP, "11", "AP SOP v4.0 §11"))
    assert citation_correct(either, SOP, "8.2 and 11", [])
    ts = card(cite(TX, "Interview 1 [02:30]"))
    assert citation_correct(ts, TX, "Interview 1 [02:30]", [])
    assert not citation_correct(ts, TX, "Interview 1 [02:31]", [], lenient=True)
    assert not citation_correct(card(cite("other.docx", "4.2")), SOP, "4.2", [])
    alt = card(cite(TX, "Video 1 [04:30]"))
    assert citation_correct(alt, SOP, "4.2", [f"{TX} Video 1 [04:30]"])
    words = card(cite(SOP, "Section 4.2 Price tolerance"))
    assert not citation_correct(words, SOP, "4.2", [])
    assert citation_correct(words, SOP, "4.2", [], lenient=True)
    sub = card(cite(SOP, "4.2.1", "AP SOP v4.0 §4.2.1"))
    assert not citation_correct(sub, SOP, "4.2", []) and citation_correct(sub, SOP, "4.2", [], True)


def test_outdated_only_counts_the_current_rule_part() -> None:
    assert outdated(card(text="The limit is the lower of 2% or ₹1,000 [1]."), "2% or ₹1,000")
    assert outdated(card(text="Lower of 2 % and Rs 1000 [1]."), "2% or ₹1,000")
    assert not outdated(card(text="Lower of 1% and ₹500 [1]."), "2% or ₹1,000")
    older = [{"older_value": "2% or ₹1,000"}]
    assert not outdated(card(text="Lower of 1% and ₹500.", older=older), "2% or ₹1,000")
    assert outdated(card(text="Runs are on Thursday."), "Thursday")
    assert not outdated(card(text="Runs are on Tuesday and Friday."), "Thursday")
    assert outdated(card(decision="Threshold ₹10 crore"), "₹10 crore")
    assert outdated(card(working=[{"label": "Cap", "value": "₹50"}]), "₹50")
    assert not outdated(card(text="anything"), None)


def test_kappa() -> None:
    a = ["correct", "wrong", "correct", "partial"]
    assert cohen_kappa(a, a) == 1.0
    assert cohen_kappa(a, ["wrong", "correct", "wrong", "correct"]) < 0


def test_scenario_text_grading_needs_every_figure_and_the_verdict() -> None:
    exp = sc.Expected("price", {"passed": False, "excess": 2500.0, "limit": 500.0})
    good = card(text="Excess ₹2,500 is above the limit of ₹500, so the line is held.")
    assert grade_scenario_text(exp, good)
    assert not grade_scenario_text(exp, card(text="Excess ₹2,500; within the limit."))
    assert not grade_scenario_text(exp, card(text="The line is held; limit ₹500."))
    msme = sc.Expected("msme", {"due_date": "2026-08-16", "run_date": "2026-08-14"})
    assert grade_scenario_text(msme, card(text="Due 16 August 2026; pay in the 14 Aug run."))


@pytest.mark.skipif(not dataset.WORKBOOK.exists(), reason="eval workbook not present")
def test_split_is_deterministic_grouped_and_stratified() -> None:
    qs = dataset.load()
    assert len(qs) == 160
    a, b = dataset.make_split(qs), dataset.make_split(qs)
    assert a == b
    share = sum(v == "dev" for v in a.values()) / len(a)
    assert 0.55 <= share <= 0.65
    by_q: dict[str, set[str]] = {}
    for q in qs:
        by_q.setdefault(" ".join(q.question.lower().split()), set()).add(a[q.id])
    assert all(len(s) == 1 for s in by_q.values())  # duplicates never straddle
    types = Counter((q.type, a[q.id]) for q in qs)
    for t in {q.type for q in qs}:
        assert types[(t, "dev")] >= 1 and types[(t, "holdout")] >= 1


def test_format_invariance_scoring_helpers() -> None:
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "scripts" / "run_format_invariance.py"
    spec = importlib.util.spec_from_file_location("fi", path)
    fi = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fi)
    assert fi.norm_text("Lower of 1% and ₹500") == fi.norm_text("lower of 1% and Rs 500")
    assert fi.f1({1, 2, 3, 4}, {1, 2, 3, 9}) == (0.75, 0.75, 0.75)
    base = ["The line passes only if the excess is small. Then post the invoice."]
    assert (
        fi.recovery(base, ["the line passes only if the excess is small. then post the invoice."])
        == 1
    )
    assert fi.recovery(base, ["Something else entirely, nothing in common here."]) == 0
