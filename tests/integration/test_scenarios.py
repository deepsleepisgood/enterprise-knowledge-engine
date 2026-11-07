"""Phase 3 acceptance: the 92 scenario questions through parameter extraction + calculators.

Test code, so it may read the evaluation workbook. The app path is the real one:
question -> MODEL_FAST parameter extraction -> calculator -> rules from the claims graph.
Grading (TEST_PLAN level 1): a question passes only if the decision and every number match.
Writes reports/scenario_results.csv and reports/scenario_misses.md.
"""

from __future__ import annotations

import csv
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from app.core.config import get_settings

ROOT = Path(__file__).resolve().parents[2]
EVAL = ROOT / "eval" / "PS-07_qa_evaluation_set.xlsx"
REPORTS = ROOT / "reports"
TODAY = date(2026, 11, 7)

pytestmark = [
    pytest.mark.db,
    pytest.mark.live_llm,
    pytest.mark.skipif(not EVAL.exists(), reason="eval workbook not present"),
    pytest.mark.skipif(not get_settings().llm_configured, reason="needs an LLM API key"),
]

FAMILY_BY_SECTION = {"4.2": "price", "6": "tds", "7": "approvals", "9": "msme", "5.4": "einvoice"}


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def _money_all(text: str) -> list[float]:
    return [_num(m) for m in re.findall(r"₹\s?([\d,]+(?:\.\d+)?)", text)]


def _date(text: str) -> list[date]:
    return [
        datetime.strptime(m, "%d %B %Y").date()
        for m in re.findall(r"(\d{1,2} [A-Z][a-z]+ \d{4})", text)
    ]


@dataclass
class Expected:
    family: str
    fields: dict[str, Any]


def expected_from_gold(section: str, gold: str) -> Expected:
    fam = FAMILY_BY_SECTION[section]
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
        due, run = _date(g)[:2]
        return Expected(fam, {"due_date": due.isoformat(), "run_date": run.isoformat()})
    return Expected(
        fam,
        {"passed": g.startswith("Yes"), "exception": "IRN_MISSING" if "IRN_MISSING" in g else None},
    )


def actual_fields(family: str, res) -> dict[str, Any]:
    r = res.result
    if family == "price":
        return {
            "passed": res.passed,
            "excess": round(r["excess"], 2),
            "limit": round(r["limit"], 2),
        }
    if family == "tds":
        if res.exception_code == "TDS_SECTION_UNCLEAR":
            return {"exception": "TDS_SECTION_UNCLEAR"}
        if "options" in r:
            return {"options": r["options"]}
        return {"section": r["section"], "rate": r["rate"], "amount": round(r["amount"], 2)}
    if family == "approvals":
        return {"decision": res.decision}
    if family == "msme":
        return {"due_date": r["due_date"], "run_date": r["run_date"]}
    return {"passed": res.passed, "exception": res.exception_code}


def _same(exp: dict[str, Any], got: dict[str, Any]) -> bool:
    for k, v in exp.items():
        g = got.get(k)
        if isinstance(v, float):
            if g is None or abs(float(g) - v) > 0.01:
                return False
        elif g != v:
            return False
    return True


@pytest.fixture(scope="module")
def scenario_results(built_graph, pack):
    from app.calc.base import DbRules
    from app.calc.params import calculator_inputs, extract_params
    from app.calc.registry import run
    from app.core.db import session_scope

    q = pd.read_excel(EVAL, sheet_name="questions")
    rows = q[q.question_type == "scenario"].to_dict(orient="records")

    def extract(row):
        try:
            return extract_params(row["question"]), None
        except Exception as exc:
            return None, f"extraction: {type(exc).__name__}: {exc}"

    with ThreadPoolExecutor(max_workers=6) as pool:
        extracted = list(pool.map(extract, rows))

    out = []
    with session_scope() as s:
        rules = DbRules(s, today=TODAY)
        for row, (params, err) in zip(rows, extracted, strict=True):
            exp = expected_from_gold(str(row["gold_source_section"]), row["gold_answer"])
            rec = {
                "id": row["question_id"],
                "question": row["question"],
                "gold": row["gold_answer"],
                "expected_family": exp.family,
                "expected": exp.fields,
                "family": None,
                "got": None,
                "decision": None,
                "ok": False,
                "cause": err,
            }
            if params is not None:
                rec["family"] = params.family
                try:
                    inputs = calculator_inputs(params, pack)
                    if params.family != exp.family or inputs is None:
                        rec["cause"] = f"routing: extracted family {params.family!r}"
                    else:
                        res = run(params.family, inputs, rules)
                        rec["got"] = actual_fields(params.family, res)
                        rec["decision"] = res.decision
                        rec["ok"] = _same(exp.fields, rec["got"])
                        if not rec["ok"]:
                            rec["cause"] = f"mismatch; inputs={inputs}"
                except Exception as exc:
                    rec["cause"] = f"calculator: {type(exc).__name__}: {exc}"
            out.append(rec)
    _write_reports(out)
    return {r["id"]: r for r in out}


def _write_reports(out: list[dict[str, Any]]) -> None:
    REPORTS.mkdir(exist_ok=True)
    with (REPORTS / "scenario_results.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "id",
                "ok",
                "expected_family",
                "family",
                "expected",
                "got",
                "decision",
                "cause",
                "question",
            ],
        )
        w.writeheader()
        for r in out:
            w.writerow({k: r[k] for k in w.fieldnames})
    misses = [r for r in out if not r["ok"]]
    lines = [f"# Scenario misses — {len(out) - len(misses)} of {len(out)} correct", ""]
    for r in misses:
        lines += [
            f"## {r['id']} ({r['expected_family']})",
            f"- Question: {r['question']}",
            f"- Gold: {r['gold']}",
            f"- Expected: {r['expected']}",
            f"- Got: {r['got']}",
            f"- Engine decision: {r['decision']}",
            f"- Cause: {r['cause']}",
            "",
        ]
    (REPORTS / "scenario_misses.md").write_text("\n".join(lines), encoding="utf-8")


def _ids() -> list[str]:
    if not EVAL.exists():
        return []
    q = pd.read_excel(EVAL, sheet_name="questions")
    return list(q[q.question_type == "scenario"].question_id)


@pytest.mark.parametrize("qid", _ids())
def test_scenario(scenario_results, qid) -> None:
    r = scenario_results[qid]
    assert r["ok"], f"{qid}: {r['cause']} | expected {r['expected']} got {r['got']}"
