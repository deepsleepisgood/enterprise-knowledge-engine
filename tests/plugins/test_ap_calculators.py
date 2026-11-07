"""Calculator unit tests (TEST_PLAN level 1 boundary cases).

Rules come from a fake lookup holding the SOP v4.0 / CM-INF-02 values as *test data*;
the calculators themselves contain no thresholds.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from app.calc.registry import run
from app.graph.rules import RuleNotFound, RuleValue

LAKH, CRORE = 100_000, 10_000_000
MEMO_TO = date(2027, 3, 31)


def _rv(
    topic,
    parameter,
    number=None,
    text="",
    items=None,
    client="all",
    vtype="number",
    src="sop_v4",
    invalid_at=None,
) -> RuleValue:
    return RuleValue(
        claim_id=hash((topic, parameter, client)) & 0xFFFF,
        topic=topic,
        parameter=parameter,
        client=client,
        value={"type": vtype, "number": number, "text": text, "items": items},
        statement=text or str(number),
        status="current",
        source_id=src,
        source_label="CM-INF-02" if src == "cm_inf_02" else "SOP v4.0",
        locator="4.3",
        passage_id=None,
        valid_at=None,
        invalid_at=invalid_at,
    )


GENERAL: dict[tuple[str, str], RuleValue] = {
    ("price_tolerance", "pct_of_line"): _rv("price_tolerance", "pct_of_line", 1),
    ("price_tolerance", "cap_inr"): _rv("price_tolerance", "cap_inr", 500),
    ("quantity_tolerance", "pct"): _rv("quantity_tolerance", "pct", 0, "none"),
    ("approvals", "controller_above_lakh"): _rv("approvals", "controller_above_lakh", 10 * LAKH),
    ("approvals", "cfo_above_lakh"): _rv("approvals", "cfo_above_lakh", 50 * LAKH),
    ("einvoice", "aato_threshold_crore"): _rv("einvoice", "aato_threshold_crore", 5 * CRORE),
    ("msme", "max_term_days"): _rv("msme", "max_term_days", 45),
    ("msme", "no_agreement_days"): _rv("msme", "no_agreement_days", 15),
    ("payments", "default_term_days"): _rv("payments", "default_term_days", 60),
    ("payments", "run_days"): _rv(
        "payments", "run_days", items=["Tuesday", "Friday"], text="Tuesday and Friday", vtype="list"
    ),
    ("payments", "cutoff"): _rv("payments", "cutoff", text="1 pm on the previous working day"),
    ("tds", "no_pan_rate"): _rv("tds", "no_pan_rate", 20),
    ("tds", "goods_purchase_threshold_inr"): _rv("tds", "goods_purchase_threshold_inr", 50 * LAKH),
    ("tds", "rate_contract_individual_huf"): _rv("tds", "rate_contract_individual_huf", 1, "194C"),
    ("tds", "rate_contract_other"): _rv("tds", "rate_contract_other", 2, "194C"),
    ("tds", "rate_professional"): _rv("tds", "rate_professional", 10, "194J"),
    ("tds", "rate_technical_service"): _rv("tds", "rate_technical_service", 2, "194J"),
    ("tds", "rate_rent_plant_machinery"): _rv("tds", "rate_rent_plant_machinery", 2, "194I"),
    ("tds", "rate_rent_land_building"): _rv("tds", "rate_rent_land_building", 10, "194I"),
    ("tds", "rate_goods_purchase"): _rv("tds", "rate_goods_purchase", 0.1, "194Q"),
}
INFRA: dict[tuple[str, str], RuleValue] = {
    ("quantity_tolerance", "pct"): _rv(
        "quantity_tolerance", "pct", 5, client="infra", src="cm_inf_02", invalid_at=MEMO_TO
    ),
    ("quantity_tolerance", "cap_value_inr"): _rv(
        "quantity_tolerance",
        "cap_value_inr",
        25_000,
        client="infra",
        src="cm_inf_02",
        invalid_at=MEMO_TO,
    ),
    ("quantity_tolerance", "materials"): _rv(
        "quantity_tolerance",
        "materials",
        client="infra",
        src="cm_inf_02",
        vtype="list",
        items=["cement", "reinforcement steel", "sand", "aggregates"],
        invalid_at=MEMO_TO,
    ),
}


class FakeRules:
    """Client rule first, then general; expiry applied on as_of like rules.get_rule."""

    def get(self, topic, parameter, client=None, as_of=None) -> RuleValue:
        if client == "infra":
            r = INFRA.get((topic, parameter))
            if r and not (as_of and r.invalid_at and as_of > r.invalid_at):
                return r
        if (topic, parameter) in GENERAL:
            return GENERAL[(topic, parameter)]
        raise RuleNotFound(f"{topic}.{parameter}")


R = FakeRules()


def calc(family: str, **params: Any):
    return run(family, params, R)


# --- price ------------------------------------------------------------------------------


def test_price_t5_cap_applies() -> None:
    r = calc("price", po_unit_price=395, invoice_unit_price=400, quantity=500)
    assert r.result["excess"] == 2500 and r.result["pct_limit"] == pytest.approx(1975)
    assert r.result["limit"] == 500 and not r.passed and r.exception_code == "PRICE_VAR"
    labels = [s.label for s in r.working]
    assert "Cap" in labels and "Limit (lower of the two)" in labels


def test_price_excess_equal_to_limit_passes() -> None:
    r = calc("price", po_unit_price=1000, invoice_unit_price=1001, quantity=500)  # 500 vs 500
    assert r.result["excess"] == 500 and r.result["limit"] == 500 and r.passed


def test_price_one_percent_below_cap_shadowing_case() -> None:
    # ₹30,000 line: 1% = ₹300 < ₹500, so the limit is ₹300; ₹460 excess fails
    r = calc("price", po_unit_price=300, invoice_unit_price=304.6, quantity=100)
    assert r.result["limit"] == pytest.approx(300) and not r.passed


def test_price_invoice_below_po_passes_at_invoice_price() -> None:
    r = calc("price", po_unit_price=400, invoice_unit_price=390, quantity=10)
    assert r.passed and "invoice price" in r.decision and r.exception_code is None


def test_price_cites_rules() -> None:
    r = calc("price", po_unit_price=395, invoice_unit_price=400, quantity=500)
    assert {c.parameter for c in r.citations} == {"pct_of_line", "cap_inr"}


# --- approvals --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("total", "expected"),
    [
        (10.00 * LAKH, "No approval beyond a clean match"),
        (10.01 * LAKH, "AP Controller"),
        (50.00 * LAKH, "AP Controller"),
        (50.01 * LAKH, "Client CFO"),
    ],
)
def test_approval_boundaries(total, expected) -> None:
    assert calc("approvals", total_incl_gst=total).decision == expected


def test_non_po_adds_budget_owner() -> None:
    r = calc("approvals", total_incl_gst=30 * LAKH, po_backed=False)
    assert r.result["approvers"] == ["AP Controller", "Budget owner"]
    small = calc("approvals", total_incl_gst=2 * LAKH, po_backed=False)
    assert small.result["approvers"] == ["Budget owner"]


# --- e-invoice --------------------------------------------------------------------------


def test_einvoice_threshold_is_exceeded_not_equal() -> None:
    assert calc("einvoice", aato=5.0 * CRORE, has_irn=False).passed  # exactly 5 crore: not required


def test_einvoice_below_threshold_with_irn_ok() -> None:
    assert calc("einvoice", aato=4.8 * CRORE, has_irn=True).passed


def test_einvoice_missing_irn_pays_nothing() -> None:
    r = calc("einvoice", aato=45 * CRORE, has_irn=False)
    assert not r.passed and r.exception_code == "IRN_MISSING" and "pay nothing" in r.decision


# --- MSME and payment runs ---------------------------------------------------------------


def test_msme_micro_no_agreement_sunday_due() -> None:
    r = calc("msme", category="micro", acceptance_date=date(2026, 8, 1))
    assert r.result["due_date"] == "2026-08-16"  # Sunday
    assert r.result["run_date"] == "2026-08-14"  # previous Friday


def test_msme_small_agreed_60_capped_at_45() -> None:
    r = calc(
        "msme",
        category="small",
        acceptance_date=date(2026, 7, 1),
        agreed_term_days=60,
        written_agreement=True,
    )
    assert r.result["term_days"] == 45


def test_msme_medium_no_agreement_60_days() -> None:
    r = calc("msme", category="medium", acceptance_date=date(2026, 8, 2))
    assert r.result["due_date"] == "2026-10-01" and r.result["run_date"] == "2026-09-29"


@pytest.mark.parametrize(
    ("accepted", "due"), [(date(2026, 7, 13), "2026-07-28"), (date(2026, 7, 16), "2026-07-31")]
)
def test_msme_due_on_run_day_pays_that_day(accepted, due) -> None:  # Tue 28 Jul / Fri 31 Jul
    r = calc("msme", category="small", acceptance_date=accepted)
    assert r.result["due_date"] == due == r.result["run_date"]


def test_msme_shows_cutoff_and_holiday_assumption() -> None:
    r = calc("msme", category="micro", acceptance_date=date(2026, 8, 1))
    cutoff = next(s.value for s in r.working if s.label == "Cut-off")
    assert "1 pm" in cutoff and "Thursday 13 August 2026" in cutoff
    assert any("holiday" in n for n in r.notes)


# --- TDS --------------------------------------------------------------------------------


def test_tds_t6_software_support() -> None:
    r = calc("tds", nature="technical_service", taxable_value=480_000)
    assert r.result["section"] == "194J" and r.result["rate"] == 2 and r.result["amount"] == 9600


def test_tds_no_pan_takes_higher_rate() -> None:
    assert (
        calc("tds", nature="professional", taxable_value=18_000, pan_available=False).result[
            "amount"
        ]
        == 3600
    )  # 20% beats 10%
    assert (
        calc("tds", nature="technical_service", taxable_value=100_000, pan_available=False).result[
            "rate"
        ]
        == 20
    )


def test_tds_contract_payee_type() -> None:
    assert calc("tds", nature="contract_individual_huf", taxable_value=100_000).result["rate"] == 1
    assert calc("tds", nature="contract_other", taxable_value=100_000).result["rate"] == 2
    both = calc("tds", nature="contract_unknown_payee", taxable_value=100_000)
    assert [o["rate"] for o in both.result["options"]] == [1, 2]


def test_tds_amc_mapping_and_unclear() -> None:
    assert calc("tds", nature="amc_technical", taxable_value=50_000).result["rate"] == 2
    lift = calc("tds", nature="amc_manpower", taxable_value=50_000)
    assert [o["section"] for o in lift.result["options"]] == ["194C", "194C"]
    cctv = calc("tds", nature="amc_unclear", taxable_value=50_000)
    assert cctv.exception_code == "TDS_SECTION_UNCLEAR" and cctv.next_owner == "Tax Desk"


def test_tds_194q_only_on_excess() -> None:
    below = calc(
        "tds", nature="goods_purchase", taxable_value=10 * LAKH, purchases_before_inr=30 * LAKH
    )
    assert below.result["amount"] == 0
    above = calc(
        "tds", nature="goods_purchase", taxable_value=10 * LAKH, purchases_before_inr=45 * LAKH
    )
    assert above.result["amount"] == pytest.approx(5 * LAKH * 0.001)


def test_tds_legal_by_advocate_flags_rcm() -> None:
    r = calc("tds", nature="professional", taxable_value=100_000, reverse_charge_service=True)
    assert r.exception_code == "RCM_REVIEW"


# --- quantity ---------------------------------------------------------------------------


def _qty(inv, grn=1000, price=500, material="cement", client="infra", day=date(2026, 11, 7)):
    return calc(
        "quantity",
        grn_quantity=grn,
        invoice_quantity=inv,
        unit_price=price,
        material=material,
        client=client,
        invoice_date=day,
    )


def test_quantity_infra_cement_within_both_limits() -> None:
    assert _qty(1049, price=489.8).passed  # 4.9%, ₹24,000


def test_quantity_infra_over_pct_or_value() -> None:
    assert _qty(1051, price=100).exception_code == "QTY_VAR"  # 5.1%
    assert _qty(1040, price=700).exception_code == "QTY_VAR"  # 4%, ₹28,000 > ₹25,000


def test_quantity_material_and_client_and_expiry() -> None:
    assert not _qty(1010, material="paint").passed
    assert not _qty(1010, client="retail", material="reinforcement steel").passed
    assert _qty(1010, material="steel").passed
    assert not _qty(1010, day=date(2027, 4, 1)).passed  # memo expired


def test_short_invoicing_passes() -> None:
    assert _qty(900, client="retail").passed


def test_missing_rule_raises_never_defaults() -> None:
    class Empty:
        def get(self, *a, **k):
            raise RuleNotFound("nothing")

    with pytest.raises(RuleNotFound):
        run("price", {"po_unit_price": 1, "invoice_unit_price": 2, "quantity": 1}, Empty())
