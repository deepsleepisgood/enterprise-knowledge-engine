"""E-invoice check: required when the highest turnover exceeds the threshold."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.calc.base import CalcResult, Rules, Step, config, inr, rule


class EinvoiceInput(BaseModel):
    aato: float = Field(ge=0, description="Highest aggregate annual turnover, in base currency")
    has_irn: bool
    client: str | None = None


def calculate(inp: EinvoiceInput, rules: Rules) -> CalcResult:
    cfg = config("einvoice")
    res = CalcResult(family="einvoice", decision="", passed=None)
    r_thr = res.cite(rule(rules, cfg, "threshold", inp.client))
    required = inp.aato > r_thr.number  # "exceeded": equal to the threshold is not required
    res.working = [
        Step("Highest turnover (AATO)", inr(inp.aato)),
        Step("E-invoice required above", inr(r_thr.number)),
        Step("E-invoice required?", "Yes" if required else "No"),
        Step("IRN on the invoice?", "Yes" if inp.has_irn else "No"),
    ]
    if required and not inp.has_irn:
        res.passed = False
        res.exception_code = cfg["exception"]
        res.decision = (
            "Not acceptable — return for an e-invoice; pay nothing, including the base value"
        )
        res.next_owner = "Supplier"
    else:
        res.passed = True
        res.decision = "Acceptable on the e-invoice check"
    res.result = {"required": required}
    return res
