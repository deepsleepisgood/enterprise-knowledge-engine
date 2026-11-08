"""Deterministic grading of scenario questions (TEST_PLAN level 1): decision and every number.

Evaluation code: it reads gold answers from the evaluation workbook, so it never lives under
app/ (tests/test_no_leakage.py).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

FAMILY_BY_SECTION = {"4.2": "price", "6": "tds", "7": "approvals", "9": "msme", "5.4": "einvoice"}


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def _dates(text: str) -> list:
    return [
        datetime.strptime(m, "%d %B %Y").date()
        for m in re.findall(r"(\d{1,2} [A-Z][a-z]+ \d{4})", text)
    ]


@dataclass
class Expected:
    family: str
    fields: dict[str, Any]


def expected_from_gold(section: str, gold: str) -> Expected:
    fam = FAMILY_BY_SECTION[str(section)]
    g = gold.strip()
    if fam == "price":
        excess = _num(re.search(r"Excess ₹([\d,]+(?:\.\d+)?)", g).group(1))
        limit = _num(re.findall(r"=\s*₹([\d,]+(?:\.\d+)?)", g)[-1])
        return Expected(fam, {"passed": g.startswith("Yes"), "excess": excess, "limit": limit})
    if fam == "tds":
        if "TDS_SECTION_UNCLEAR" in g:
            return Expected(fam, {"exception": "TDS_SECTION_UNCLEAR"})
        sec = re.search(r"\b(19\d[A-Z])\b", g).group(1)
        rate = _num(re.search(r"at ([\d.]+)%", g).group(1))
        amount = _num(re.search(r":\s*₹([\d,]+(?:\.\d+)?)", g).group(1))
        return Expected(fam, {"section": sec, "rate": rate, "amount": amount})
    if fam == "approvals":
        return Expected(fam, {"decision": g.split(" (")[0].rstrip(".")})
    if fam == "msme":
        due, run = _dates(g)[:2]
        return Expected(fam, {"due_date": due.isoformat(), "run_date": run.isoformat()})
    return Expected(
        fam,
        {"passed": g.startswith("Yes"), "exception": "IRN_MISSING" if "IRN_MISSING" in g else None},
    )


def actual_fields(
    family: str, passed: Any, decision: str, exception: str | None, r: dict[str, Any]
) -> dict[str, Any]:
    """The graded fields of a calculator result (from a CalcResult or a card's diagnostics)."""
    if family == "price":
        return {"passed": passed, "excess": round(r["excess"], 2), "limit": round(r["limit"], 2)}
    if family == "tds":
        if exception == "TDS_SECTION_UNCLEAR":
            return {"exception": "TDS_SECTION_UNCLEAR"}
        if "options" in r:
            return {"options": r["options"]}
        return {"section": r["section"], "rate": r["rate"], "amount": round(r["amount"], 2)}
    if family == "approvals":
        return {"decision": decision}
    if family == "msme":
        return {"due_date": r["due_date"], "run_date": r["run_date"]}
    return {"passed": passed, "exception": exception}


def from_calc(family: str, res: Any) -> dict[str, Any]:
    return actual_fields(family, res.passed, res.decision, res.exception_code, res.result)


def from_card(card: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
    """(family, graded fields) from an answer card's calculator diagnostics, if it ran."""
    c = (card.get("diagnostics") or {}).get("calculator")
    if not c:
        return None, None
    try:
        return c["family"], actual_fields(
            c["family"], c["passed"], c["decision"], c["exception_code"], c["result"]
        )
    except (KeyError, TypeError):
        return c.get("family"), None


def same(exp: dict[str, Any], got: dict[str, Any] | None) -> bool:
    if got is None:
        return False
    for k, v in exp.items():
        g = got.get(k)
        if isinstance(v, float):
            if g is None or abs(float(g) - v) > 0.01:
                return False
        elif g != v:
            return False
    return True
