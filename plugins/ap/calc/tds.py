"""TDS: section and rate by nature of payment, on the value excluding GST."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from app.calc.base import CalcResult, Rules, Step, config, inr, pct, rule
from app.graph.rules import RuleValue


class TdsInput(BaseModel):
    nature: str = Field(description="A key from tds_natures in the pack")
    taxable_value: float = Field(ge=0, description="Value excluding GST")
    pan_available: bool = True
    purchases_before_inr: float | None = Field(
        None, description="Goods only: purchases from this supplier earlier in the year"
    )
    reverse_charge_service: bool = False
    client: str | None = None


def section_of(r: RuleValue) -> str:
    text = " ".join(str(r.value.get(k) or "") for k in ("text", "items")) + " " + r.statement
    m = re.search(r"\b(19\d[A-Z]?)\b", text)
    return m.group(1) if m else "?"


def _rate_line(
    res: CalcResult, rules: Rules, cfg: dict, key: str, inp: TdsInput, base: float, label: str
) -> dict:
    r = res.cite(rule(rules, cfg, key, inp.client))
    rate = r.number
    if not inp.pan_available:
        r_np = res.cite(rule(rules, cfg, "no_pan_rate", inp.client))
        rate = max(rate, r_np.number)
    amount = round(base * rate / 100, 2)
    res.working.append(Step(f"{label}: section {section_of(r)} at {pct(rate)}", inr(amount)))
    return {"section": section_of(r), "rate": rate, "amount": amount, "normal_rate": r.number}


def calculate(inp: TdsInput, rules: Rules) -> CalcResult:
    cfg = config("tds")
    res = CalcResult(family="tds", decision="", passed=None)
    res.working.append(Step("Base (taxable value, GST excluded)", inr(inp.taxable_value)))
    nature = cfg.get("amc", {}).get(inp.nature, inp.nature)

    if nature == "unclear":
        res.exception_code = cfg["unclear_exception"]
        res.next_owner = cfg["route"]
        res.decision = f"Section unclear — raise {cfg['unclear_exception']} to the {cfg['route']}"
        return res

    base = inp.taxable_value
    if nature == "goods_purchase":
        r_thr = res.cite(rule(rules, cfg, "goods_threshold", inp.client))
        before = inp.purchases_before_inr or 0.0
        base = max(0.0, before + inp.taxable_value - r_thr.number) - max(0.0, before - r_thr.number)
        res.working.append(Step(f"Taxable excess over {inr(r_thr.number)} in the year", inr(base)))

    if not inp.pan_available:
        res.working.append(
            Step("PAN furnished?", "No — higher of the no-PAN rate and the normal rate")
        )

    if nature in ("contract", "contract_unknown_payee"):
        a = _rate_line(res, rules, cfg, "contract_individual_huf", inp, base, "If individual/HUF")
        b = _rate_line(res, rules, cfg, "contract_other", inp, base, "If company/other")
        res.decision = (
            f"Section {a['section']}: {pct(a['rate'])} ({inr(a['amount'])}) if the payee is "
            f"an individual or HUF, else {pct(b['rate'])} ({inr(b['amount'])})"
        )
        res.result = {"options": [a, b]}
    else:
        line = _rate_line(res, rules, cfg, nature, inp, base, "TDS")
        res.decision = f"Section {line['section']} at {pct(line['rate'])}: {inr(line['amount'])}"
        res.result = line
    if inp.reverse_charge_service:
        res.exception_code = cfg["rcm_exception"]
        res.next_owner = cfg["route"]
        res.notes.append(
            f"Reverse-charge service: flag {cfg['rcm_exception']} for the {cfg['route']}."
        )
    res.passed = True
    return res
