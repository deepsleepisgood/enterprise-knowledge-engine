"""Phase 3 acceptance: the 92 scenario questions through the real application path.

Test code, so it may read the evaluation workbook. Path: corpus -> generic ingestion -> schema
(induced, or the plug-in baseline) -> extraction -> authority resolution -> plug-in bindings ->
question -> MODEL_FAST parameter extraction -> plug-in calculator over bound facts.
Grading (TEST_PLAN level 1): a question passes only if the decision and every number match.
Each schema mode runs in its own tenant: SCENARIO_MODES=induced,baseline (default: induced).
Writes reports/scenario_results_<mode>.csv and reports/scenario_misses_<mode>.md.
"""

from __future__ import annotations

import csv
import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from app.core.config import get_settings
from tests.live_graph import build_tenant

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

MODES = [m.strip() for m in os.environ.get("SCENARIO_MODES", "induced").split(",") if m.strip()]

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


def run_scenarios(mode: str) -> dict[str, dict[str, Any]]:
    from app.core.db import session_scope
    from app.graph import pipeline as gp
    from app.plugins.calculate import calculate
    from app.store import entities
    from app.store.base import use_tenant
    from plugins.ap.calc.params import calculator_inputs, extract_params

    q = pd.read_excel(EVAL, sheet_name="questions")
    rows = q[q.question_type == "scenario"].to_dict(orient="records")
    with use_tenant(mode), session_scope() as s:
        clients = [e.name for e in entities.list_entities(s, "client")]
        onto = gp.active_ontology(s, mode)

    def extract(row):
        try:
            return extract_params(row["question"], clients), None
        except Exception as exc:
            return None, f"extraction: {type(exc).__name__}: {exc}"

    with ThreadPoolExecutor(max_workers=6) as pool:
        extracted = list(pool.map(extract, rows))

    out = []
    with use_tenant(mode), session_scope() as s:
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
                    inputs = calculator_inputs(params, onto.units, clients, onto.base_currency)
                    if params.family != exp.family or inputs is None:
                        rec["cause"] = f"routing: extracted family {params.family!r}"
                    else:
                        res = calculate(s, onto, "ap", params.family, inputs, today=TODAY)
                        rec["got"] = actual_fields(params.family, res)
                        rec["decision"] = res.decision
                        rec["ok"] = _same(exp.fields, rec["got"])
                        if not rec["ok"]:
                            rec["cause"] = f"mismatch; inputs={inputs}"
                except Exception as exc:
                    rec["cause"] = f"calculator: {type(exc).__name__}: {exc}"
            out.append(rec)
    _write_reports(out, mode)
    return {r["id"]: r for r in out}


@pytest.fixture(scope="module")
def scenario_results(database_url) -> dict[str, dict[str, dict[str, Any]]]:
    out = {}
    for mode in MODES:
        build_tenant(mode)
        out[mode] = run_scenarios(mode)
    return out


def _write_reports(out: list[dict[str, Any]], mode: str) -> None:
    REPORTS.mkdir(exist_ok=True)
    with (REPORTS / f"scenario_results_{mode}.csv").open("w", newline="", encoding="utf-8") as f:
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
    lines = [
        f"# Scenario misses ({mode} schema) — {len(out) - len(misses)} of {len(out)} correct",
        "",
    ]
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
    (REPORTS / f"scenario_misses_{mode}.md").write_text("\n".join(lines), encoding="utf-8")


def _ids() -> list[str]:
    if not EVAL.exists():
        return []
    q = pd.read_excel(EVAL, sheet_name="questions")
    return list(q[q.question_type == "scenario"].question_id)


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("qid", _ids())
def test_scenario(scenario_results, mode, qid) -> None:
    r = scenario_results[mode][qid]
    assert r["ok"], f"{mode} {qid}: {r['cause']} | expected {r['expected']} got {r['got']}"
