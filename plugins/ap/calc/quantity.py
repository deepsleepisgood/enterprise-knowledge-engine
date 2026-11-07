"""Quantity tolerance: no excess over GRN, unless a client rule allows it for listed materials."""

from __future__ import annotations

import re
from datetime import date

from pydantic import BaseModel, Field

from app.graph.rules import RuleNotFound

from .base import CalcResult, Rules, Step, config, inr, pct, rule

EPS = 1e-9


class QuantityInput(BaseModel):
    grn_quantity: float = Field(gt=0)
    invoice_quantity: float = Field(ge=0)
    unit_price: float = Field(ge=0)
    material: str
    client: str | None = None
    invoice_date: date | None = None


def _norm(s: str) -> str:
    return re.sub(r"[^a-z ]+", " ", s.lower()).replace("  ", " ").strip().rstrip("s")


def _material_listed(material: str, items: list[str]) -> bool:
    m = _norm(material)
    return any(m and (m in _norm(i) or _norm(i) in m) for i in items if _norm(i))


def calculate(inp: QuantityInput, rules: Rules) -> CalcResult:
    cfg = config("quantity")
    res = CalcResult(family="quantity", decision="", passed=None)
    excess_qty = max(0.0, inp.invoice_quantity - inp.grn_quantity)
    excess_value = excess_qty * inp.unit_price
    excess_pct = excess_qty / inp.grn_quantity * 100
    res.working = [
        Step("GRN quantity", f"{inp.grn_quantity:g}"),
        Step("Invoice quantity", f"{inp.invoice_quantity:g}"),
        Step("Excess quantity", f"{excess_qty:g} ({excess_pct:.2f}%)"),
        Step("Excess value", inr(excess_value)),
    ]
    if excess_qty == 0:
        res.passed = True
        res.decision = "Pass — invoice quantity does not exceed the GRN (any balance stays open)"
        res.cite(rule(rules, cfg, "pct", inp.client, inp.invoice_date))
        return res

    r_pct = res.cite(rule(rules, cfg, "pct", inp.client, inp.invoice_date))
    allowed = False
    if r_pct.number > 0 and r_pct.client not in (None, "all"):
        try:
            r_mat = res.cite(rule(rules, cfg, "materials", inp.client, inp.invoice_date))
            r_cap = res.cite(rule(rules, cfg, "cap_value", inp.client, inp.invoice_date))
        except RuleNotFound as exc:
            raise RuleNotFound(f"client quantity tolerance is incomplete: {exc}") from exc
        listed = _material_listed(inp.material, r_mat.value.get("items") or [])
        res.working += [
            Step(f"Material covered by {r_pct.citation}?", "Yes" if listed else "No"),
            Step("Tolerance", f"{pct(r_pct.number)} of GRN quantity, max {inr(r_cap.number)}"),
        ]
        allowed = listed and excess_pct <= r_pct.number + EPS and excess_value <= r_cap.number + EPS
    else:
        res.working.append(Step("Tolerance", "None"))

    res.passed = allowed
    if allowed:
        res.decision = "Pass — within the client's bulk-material tolerance"
    else:
        res.decision = "Hold — invoice quantity above GRN"
        res.exception_code = cfg["exception"]
        res.next_owner = cfg.get("next_owner")
    res.result = {"excess_qty": excess_qty, "excess_value": excess_value, "excess_pct": excess_pct}
    return res
