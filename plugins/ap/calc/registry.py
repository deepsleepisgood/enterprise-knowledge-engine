"""Calculator registry: family name -> (input model, function)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from . import approvals, einvoice, msme, price, quantity, tds
from .base import CalcResult, Rules

CALCULATORS: dict[str, tuple[type[BaseModel], Callable[[Any, Rules], CalcResult]]] = {
    "price": (price.PriceInput, price.calculate),
    "quantity": (quantity.QuantityInput, quantity.calculate),
    "approvals": (approvals.ApprovalsInput, approvals.calculate),
    "einvoice": (einvoice.EinvoiceInput, einvoice.calculate),
    "msme": (msme.MsmeInput, msme.calculate),
    "tds": (tds.TdsInput, tds.calculate),
}


DESCRIPTIONS = {
    "price": "invoice unit price vs PO unit price on a line: within price tolerance?",
    "quantity": "invoice quantity vs goods-receipt (GRN) quantity: within quantity tolerance?",
    "approvals": "who must approve an invoice of a given total value",
    "einvoice": "is an invoice without an IRN / e-invoice acceptable, given supplier turnover",
    "msme": "due date and payment run for an MSME supplier's invoice",
    "tds": "TDS section, rate and amount to deduct on a specific invoice",
}


def describe() -> dict[str, str]:
    """Calculator family -> what a question for it looks like (shown to the core's router)."""
    return dict(DESCRIPTIONS)


def inputs_for(
    question: str,
    clients: list[str],
    units: dict[str, float],
    base: str | None = None,
    structured_fn: Any = None,
) -> tuple[str, dict[str, Any]] | None:
    """Extract a calculator's inputs from a question; None when it is not a calculation."""
    from .params import calculator_inputs, extract_params

    p = extract_params(question, clients, structured_fn)
    inputs = calculator_inputs(p, units, clients, base)
    return (p.family, inputs) if inputs is not None else None


def run(family: str, params: dict[str, Any] | BaseModel, rules: Rules) -> CalcResult:
    model, fn = CALCULATORS[family]
    inp = params if isinstance(params, model) else model.model_validate(params)
    return fn(inp, rules)
