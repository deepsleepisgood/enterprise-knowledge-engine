"""Price tolerance: excess over the PO price vs the lower of a % of line value and a cap.

Two ways a line is described: unit prices and a quantity ("PO ₹395 for 200 units, invoice
₹398"), or the PO line value and the excess directly ("a ₹340 difference on a ₹12,000 line").
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from .base import CalcResult, Rules, Step, config, inr, pct, rule

EPS = 1e-9


class PriceInput(BaseModel):
    po_unit_price: float | None = Field(None, gt=0)
    invoice_unit_price: float | None = Field(None, ge=0)
    quantity: float | None = Field(None, gt=0)
    po_line_value: float | None = Field(None, gt=0)
    excess: float | None = Field(None, ge=0)
    client: str | None = None

    @model_validator(mode="after")
    def _one_form(self) -> PriceInput:
        units = None not in (self.po_unit_price, self.invoice_unit_price, self.quantity)
        line = None not in (self.po_line_value, self.excess)
        if not (units or line):
            raise ValueError(
                "give the PO and invoice unit prices with the quantity, "
                "or the PO line value with the excess"
            )
        return self

    @property
    def by_units(self) -> bool:
        return None not in (self.po_unit_price, self.invoice_unit_price, self.quantity)


def calculate(inp: PriceInput, rules: Rules) -> CalcResult:
    cfg = config("price")
    r_pct = rule(rules, cfg, "pct", inp.client)
    r_cap = rule(rules, cfg, "cap", inp.client)
    res = CalcResult(family="price", decision="", passed=None)
    res.cite(r_pct)
    res.cite(r_cap)

    if inp.by_units:
        po, inv, qty = inp.po_unit_price or 0.0, inp.invoice_unit_price or 0.0, inp.quantity or 0.0
        line_value = po * qty
        per_unit = inv - po
        excess = max(0.0, per_unit) * qty
        steps = [
            Step(f"PO line value ({inr(po)} × {qty:g})", inr(line_value)),
            Step(f"Excess on line ({inr(max(0.0, per_unit))} × {qty:g})", inr(excess)),
        ]
    else:
        line_value, excess = inp.po_line_value or 0.0, inp.excess or 0.0
        per_unit = excess  # only its sign matters below
        steps = [
            Step("PO line value (as given)", inr(line_value)),
            Step("Excess on line", inr(excess)),
        ]
    pct_limit = r_pct.number / 100 * line_value
    limit = min(pct_limit, r_cap.number)

    res.working = [
        *steps,
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
