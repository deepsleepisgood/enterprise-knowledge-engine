"""Payment due date and payment run (MSME terms, run days, cut-off). Assumes no holidays."""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel

from app.graph.rules import RuleNotFound

from .base import CalcResult, Rules, Step, config, fmt_day, rule

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


class MsmeInput(BaseModel):
    category: Literal["micro", "small", "medium", "not_msme"]
    acceptance_date: date
    agreed_term_days: int | None = None
    written_agreement: bool = False
    client: str | None = None


def run_weekdays(value: dict) -> list[int]:
    words = " ".join([*(value.get("items") or []), value.get("text") or ""]).lower()
    days = sorted({i for i, d in enumerate(WEEKDAYS) if re.search(rf"\b{d}", words)})
    if not days:
        raise RuleNotFound(f"payment run days not readable from rule value {value!r}")
    return days


def last_run_on_or_before(d: date, weekdays: list[int]) -> date:
    for back in range(7):
        day = d - timedelta(days=back)
        if day.weekday() in weekdays:
            return day
    raise ValueError("no run day in a week")  # unreachable with at least one weekday


def previous_working_day(d: date) -> date:
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def calculate(inp: MsmeInput, rules: Rules) -> CalcResult:
    cfg = config("msme")
    res = CalcResult(family="msme", decision="", passed=None)
    if inp.category in ("micro", "small"):
        r_max = res.cite(rule(rules, cfg, "max_term", inp.client))
        if inp.written_agreement and inp.agreed_term_days:
            term = min(inp.agreed_term_days, int(r_max.number))
            basis = f"agreed {inp.agreed_term_days} days, capped at {r_max.number:g}"
        else:
            r_none = res.cite(rule(rules, cfg, "no_agreement", inp.client))
            term = int(r_none.number)
            basis = "no written agreement"
        res.exception_code = cfg.get("exception")
    else:
        if inp.agreed_term_days:
            term, basis = inp.agreed_term_days, "agreed term (normal terms)"
        else:
            r_def = res.cite(rule(rules, cfg, "default_term", inp.client))
            term, basis = int(r_def.number), "default term (normal terms)"

    due = inp.acceptance_date + timedelta(days=term)
    r_runs = res.cite(rule(rules, cfg, "run_days", inp.client))
    run = last_run_on_or_before(due, run_weekdays(r_runs.value))
    cutoff_day = previous_working_day(run)
    try:
        r_cut = res.cite(rule(rules, cfg, "cutoff", inp.client))
        cutoff = f"{r_cut.value.get('text')} → {fmt_day(cutoff_day)}"
    except RuleNotFound:
        cutoff = fmt_day(cutoff_day)

    res.working = [
        Step("Supplier category", inp.category.replace("_", " ")),
        Step("Accepted on", fmt_day(inp.acceptance_date)),
        Step("Term", f"{term} days ({basis})"),
        Step("Due date", fmt_day(due)),
        Step("Payment run (last on or before due)", fmt_day(run)),
        Step("Cut-off", cutoff),
    ]
    res.passed = True
    res.decision = f"Due {fmt_day(due)}; pay in the {fmt_day(run)} run"
    res.notes.append("Assumes no public holidays.")
    res.result = {"term_days": term, "due_date": due.isoformat(), "run_date": run.isoformat()}
    return res
