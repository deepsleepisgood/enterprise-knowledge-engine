"""Calculator parameter extraction: conversion and validation (fake LLM, no network)."""

from __future__ import annotations

from datetime import date

import pytest

from app.calc.params import (
    ApprovalsArgs,
    EinvoiceArgs,
    Money,
    ScenarioParams,
    TdsArgs,
    build_prompt,
    calculator_inputs,
    extract_params,
)


def test_money_units_converted_with_pack_table(pack) -> None:
    p = ScenarioParams(
        family="approvals",
        client="infra",
        approvals=ApprovalsArgs(total_incl_gst=Money(amount=12.5, unit="lakh"), po_backed=True),
    )
    assert calculator_inputs(p, pack) == {
        "total_incl_gst": 1_250_000,
        "po_backed": True,
        "client": "infra",
    }
    e = ScenarioParams(
        family="einvoice",
        einvoice=EinvoiceArgs(aato=Money(amount=4.8, unit="crore"), has_irn=False),
    )
    assert calculator_inputs(e, pack)["aato"] == pytest.approx(48_000_000)


def test_tds_inputs(pack) -> None:
    p = ScenarioParams(
        family="tds",
        tds=TdsArgs(
            nature="professional",
            taxable_value=Money(amount=18000, unit="INR"),
            pan_available=False,
            reverse_charge_service=False,
        ),
    )
    d = calculator_inputs(p, pack)
    assert d["taxable_value"] == 18000 and d["purchases_before_inr"] is None
    assert "purchases_before" not in d


def test_unknown_client_and_none_family(pack) -> None:
    assert calculator_inputs(ScenarioParams(family="none"), pack) is None
    p = ScenarioParams(
        family="approvals",
        client="acme",
        approvals=ApprovalsArgs(total_incl_gst=Money(amount=1, unit="lakh"), po_backed=True),
    )
    assert calculator_inputs(p, pack)["client"] is None


def test_unknown_money_unit_raises(pack) -> None:
    p = ScenarioParams(
        family="approvals",
        approvals=ApprovalsArgs(total_incl_gst=Money(amount=1, unit="gazillion"), po_backed=True),
    )
    with pytest.raises(ValueError):
        calculator_inputs(p, pack)


def test_extract_params_uses_fast_model_and_pack_natures(pack) -> None:
    calls = []

    def fake(prompt, schema, **kw):
        calls.append({"prompt": prompt, **kw})
        return ScenarioParams(family="msme")

    extract_params("When is this due?", fake, pack)
    assert calls[0]["model"] == "fast" and calls[0]["prompt_version"] == "params-v1"
    assert "amc_unclear" in calls[0]["prompt"] and "When is this due?" in calls[0]["prompt"]
    assert "technical_service" in build_prompt("q", pack)


def test_dates_parse() -> None:
    from app.calc.params import MsmeArgs

    m = MsmeArgs(category="micro", acceptance_date="2026-08-01", written_agreement=False)
    assert m.acceptance_date == date(2026, 8, 1)
