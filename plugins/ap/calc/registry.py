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


def run(family: str, params: dict[str, Any] | BaseModel, rules: Rules) -> CalcResult:
    model, fn = CALCULATORS[family]
    inp = params if isinstance(params, model) else model.model_validate(params)
    return fn(inp, rules)
