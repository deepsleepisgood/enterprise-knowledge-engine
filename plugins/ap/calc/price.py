"""Price tolerance: excess over the PO price vs the lower of a % of line value and a cap."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.calc.base import CalcResult, Rules, Step, config, inr, pct, rule

EPS = 1e-9


class PriceInput(BaseModel):
    po_unit_price: float = Field(gt=0)
    invoice_unit_price: float = Field(ge=0)
    quantity: float = Field(gt=0)
    client: str | None = None


def calculate(inp: PriceInput, rules: Rules) -> CalcResult:
    cfg = config("price")
    r_pct = rule(rules, cfg, "pct", inp.client)
    r_cap = rule(rules, cfg, "cap", inp.client)
    res = CalcResult(family="price", decision="", passed=None)
    res.cite(r_pct)
    res.cite(r_cap)

    line_value = inp.po_unit_price * inp.quantity
    per_unit = inp.invoice_unit_price - inp.po_unit_price
    excess = max(0.0, per_unit) * inp.quantity
    pct_limit = r_pct.number / 100 * line_value
    limit = min(pct_limit, r_cap.number)

    res.working = [
        Step(f"PO line value ({inr(inp.po_unit_price)} × {inp.quantity:g})", inr(line_value)),
        Step(f"Excess on line ({inr(max(0.0, per_unit))} × {inp.quantity:g})", inr(excess)),
        Step(f"{pct(r_pct.number)} of PO line value", inr(pct_limit)),
        Step("Cap", inr(r_cap.number)),
        Step("Limit (lower of the two)", inr(limit)),
    ]
    if per_unit < 0:
        res.passed = True
        res.decision = "Pass — invoice price is below the PO price; pay the invoice price"
    else:
        res.passed = excess <= limit + EPS
        res.working.append(Step("Excess within limit?", "Yes" if res.passed else "No"))
        if res.passed:
            res.decision = "Pass — excess within the price tolerance"
        else:
            res.decision = "Hold the line — price variance above tolerance"
            res.exception_code = cfg["exception"]
            res.next_owner = cfg.get("next_owner")
    res.result = {
        "line_value": line_value,
        "excess": excess,
        "pct_limit": pct_limit,
        "cap": r_cap.number,
        "limit": limit,
    }
    return res
