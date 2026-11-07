"""Read calculator inputs from a free-text question with MODEL_FAST (structured output).

Never regex the question wording (TEST_PLAN §3): the model extracts typed values, and
code converts money units with the active schema's unit words. Client names come from the
graph's client entities. Few-shot examples are invented, not taken from any evaluation
question.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

from .base import calculators_yaml

PROMPT_VERSION = "params-v2"

Family = Literal["price", "quantity", "approvals", "einvoice", "msme", "tds", "none"]


class Money(BaseModel):
    amount: float
    unit: str = Field(description="The unit as written: INR, lakh or crore")


class PriceArgs(BaseModel):
    po_unit_price: float
    invoice_unit_price: float
    quantity: float


class QuantityArgs(BaseModel):
    grn_quantity: float
    invoice_quantity: float
    unit_price: float
    material: str
    invoice_date: date | None = None


class ApprovalsArgs(BaseModel):
    total_incl_gst: Money
    po_backed: bool = Field(description="False only if the invoice is non-PO")


class EinvoiceArgs(BaseModel):
    aato: Money = Field(description="Highest aggregate annual turnover")
    has_irn: bool


class MsmeArgs(BaseModel):
    category: Literal["micro", "small", "medium", "not_msme"]
    acceptance_date: date
    agreed_term_days: int | None = None
    written_agreement: bool = Field(description="True only if written payment terms are agreed")


class TdsArgs(BaseModel):
    nature: str = Field(description="One nature key from the list")
    taxable_value: Money = Field(description="Value excluding GST")
    pan_available: bool = Field(description="False only if the supplier has no PAN")
    purchases_before: Money | None = Field(
        None, description="Goods only: purchases from the supplier earlier in the financial year"
    )
    reverse_charge_service: bool = Field(
        description="True for legal services from an advocate or a firm of advocates"
    )


class ScenarioParams(BaseModel):
    family: Family
    client: str | None = Field(
        None, description="The client named in the question, as one of the listed client names"
    )
    price: PriceArgs | None = None
    quantity: QuantityArgs | None = None
    approvals: ApprovalsArgs | None = None
    einvoice: EinvoiceArgs | None = None
    msme: MsmeArgs | None = None
    tds: TdsArgs | None = None


SYSTEM = """You read one accounts-payable question and extract the inputs a calculator needs.
Choose the family:
- price: invoice unit price vs PO unit price for a line
- quantity: invoice quantity vs goods-receipt (GRN) quantity
- approvals: who must approve an invoice of a given total
- einvoice: whether an invoice without an IRN / e-invoice is acceptable given supplier turnover
- msme: due date and payment run for a supplier's invoice
- tds: tax deducted at source on an invoice
- none: anything else
Fill only the block for that family. Copy numbers exactly as written; do not compute anything.
Money: give the amount and its unit as written (INR for plain rupee amounts, lakh, crore).
Dates: ISO format (YYYY-MM-DD). If a value is not stated, leave it null; never guess.

Example: "Supplier billed ₹12.5 per kg against a PO price of ₹12 for 800 kg. Within tolerance?"
-> family price, price {po_unit_price 12, invoice_unit_price 12.5, quantity 800}.
"""


def build_prompt(question: str, clients: list[str]) -> str:
    natures = calculators_yaml().get("tds_natures", {})
    nature_lines = "\n".join(f"- {k}: {v}" for k, v in natures.items())
    names = ", ".join(clients) or "none known"
    return f"Clients: {names}\n\nTDS nature keys:\n{nature_lines}\n\nQuestion:\n{question}"


def to_base(money: Money | None, units: dict[str, float], base: str | None = None) -> float | None:
    if money is None:
        return None
    unit = money.unit.strip().lower().rstrip(".")
    if base and unit == base.lower():
        return money.amount
    mult = {str(k).lower(): float(v) for k, v in units.items()}.get(unit)
    if mult is None:
        raise ValueError(f"unknown money unit {money.unit!r}")
    return money.amount * mult


def match_client(name: str | None, clients: list[str]) -> str | None:
    """The known client this name refers to (exact, or every word of one inside the other)."""
    if not name:
        return None
    words = set(re.findall(r"[a-z0-9]+", name.lower())) - {"ltd", "pvt", "limited", "the"}
    for c in clients:
        cw = set(re.findall(r"[a-z0-9]+", c.lower())) - {"ltd", "pvt", "limited", "the"}
        if name.lower() == c.lower() or (words and (words <= cw or cw <= words)):
            return c
    return None


def calculator_inputs(
    p: ScenarioParams,
    units: dict[str, float],
    clients: list[str],
    base: str | None = None,
) -> dict[str, Any] | None:
    """Turn extracted params into the calculator's input dict (money in base currency)."""
    block = getattr(p, p.family, None) if p.family != "none" else None
    if block is None:
        return None
    d = block.model_dump()
    if p.family == "approvals":
        d["total_incl_gst"] = to_base(block.total_incl_gst, units, base)
    elif p.family == "einvoice":
        d["aato"] = to_base(block.aato, units, base)
    elif p.family == "tds":
        d["taxable_value"] = to_base(block.taxable_value, units, base)
        d["purchases_before_inr"] = to_base(block.purchases_before, units, base)
        d.pop("purchases_before", None)
    return {**d, "client": match_client(p.client, clients)}


def extract_params(question: str, clients: list[str], structured_fn=None) -> ScenarioParams:
    if structured_fn is None:
        from app.core.llm import structured

        structured_fn = structured
    return structured_fn(
        build_prompt(question, clients),
        ScenarioParams,
        system=SYSTEM,
        model="fast",
        prompt_version=PROMPT_VERSION,
        max_tokens=4096,
    )
