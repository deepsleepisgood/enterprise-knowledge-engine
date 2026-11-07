"""Calculator parameter extraction: conversion and validation (fake LLM, no network)."""

from __future__ import annotations

from datetime import date

import pytest

from plugins.ap.calc.params import (
    ApprovalsArgs,
    EinvoiceArgs,
    Money,
    MsmeArgs,
    ScenarioParams,
    TdsArgs,
    build_prompt,
    calculator_inputs,
    extract_params,
    match_client,
)

UNITS = {"lakh": 100_000, "crore": 10_000_000, "inr": 1}
CLIENTS = ["Arvana Infra Projects Ltd", "Arvana Pharma Ltd", "Arvana Retail Pvt Ltd"]


def test_money_units_converted_with_schema_units() -> None:
    p = ScenarioParams(
        family="approvals",
        client="Arvana Infra",
        approvals=ApprovalsArgs(total_incl_gst=Money(amount=12.5, unit="lakh"), po_backed=True),
    )
    assert calculator_inputs(p, UNITS, CLIENTS, "INR") == {
        "total_incl_gst": 1_250_000,
        "po_backed": True,
        "client": "Arvana Infra Projects Ltd",
    }
    e = ScenarioParams(
        family="einvoice",
        einvoice=EinvoiceArgs(aato=Money(amount=4.8, unit="crore"), has_irn=False),
    )
    assert calculator_inputs(e, UNITS, CLIENTS)["aato"] == pytest.approx(48_000_000)


def test_tds_inputs() -> None:
    p = ScenarioParams(
        family="tds",
        tds=TdsArgs(
            nature="professional",
            taxable_value=Money(amount=18000, unit="INR"),
            pan_available=False,
            reverse_charge_service=False,
        ),
    )
    d = calculator_inputs(p, UNITS, CLIENTS, "INR")
    assert d["taxable_value"] == 18000 and d["purchases_before_inr"] is None
    assert "purchases_before" not in d


def test_unknown_client_and_none_family() -> None:
    assert calculator_inputs(ScenarioParams(family="none"), UNITS, CLIENTS) is None
    p = ScenarioParams(
        family="approvals",
        client="Acme",
        approvals=ApprovalsArgs(total_incl_gst=Money(amount=1, unit="lakh"), po_backed=True),
    )
    assert calculator_inputs(p, UNITS, CLIENTS)["client"] is None
    assert match_client("pharma", CLIENTS) == "Arvana Pharma Ltd"


def test_unknown_money_unit_raises() -> None:
    p = ScenarioParams(
        family="approvals",
        approvals=ApprovalsArgs(total_incl_gst=Money(amount=1, unit="gazillion"), po_backed=True),
    )
    with pytest.raises(ValueError):
        calculator_inputs(p, UNITS, CLIENTS)


def test_extract_params_uses_fast_model_and_plugin_natures() -> None:
    calls = []

    def fake(prompt, schema, **kw):
        calls.append({"prompt": prompt, **kw})
        return ScenarioParams(family="msme")

    extract_params("When is this due?", CLIENTS, fake)
    assert calls[0]["model"] == "fast"
    assert "amc_unclear" in calls[0]["prompt"] and "When is this due?" in calls[0]["prompt"]
    assert "Arvana Pharma Ltd" in calls[0]["prompt"]
    assert "technical_service" in build_prompt("q", CLIENTS)


def test_dates_parse() -> None:
    m = MsmeArgs(category="micro", acceptance_date="2026-08-01", written_agreement=False)
    assert m.acceptance_date == date(2026, 8, 1)
