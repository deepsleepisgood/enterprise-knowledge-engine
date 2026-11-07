"""Extraction post-processing with a fake structured call (no API)."""

from __future__ import annotations

import pytest

from app.graph.compare import LLMComparator
from app.graph.extract import (
    PassageForExtraction,
    build_prompt,
    extract_passage,
    system_prompt,
)
from app.graph.schema import CompareVerdict, ExtractedClaim, ExtractedValue, ExtractionResult


def _passage(source_id: str, text: str, locator: str = "x") -> PassageForExtraction:
    return PassageForExtraction(
        id=f"p-{source_id}",
        source_id=source_id,
        locator=locator,
        segment_kind="subsection",
        context_header="hdr",
        text=text,
    )


def _claim(**kw) -> ExtractedClaim:
    base = dict(
        topic="approvals",
        parameter="controller_above_lakh",
        client="all",
        value=ExtractedValue(type="money", number=10, unit="lakh", text="above ₹10 lakh"),
        statement="Invoices above ₹10 lakh need AP Controller approval.",
        kind="rule",
        quote="Above ₹10 lakh up to ₹50 lakh | AP Controller",
    )
    base.update(kw)
    return ExtractedClaim(**base)


class FakeLLM:
    def __init__(self, claims: list[ExtractedClaim]) -> None:
        self.claims = claims
        self.calls: list[dict] = []

    def __call__(self, prompt, schema, **kw):
        self.calls.append({"prompt": prompt, "schema": schema, **kw})
        return ExtractionResult(claims=self.claims)


def test_money_normalised_to_base_currency(pack) -> None:
    p = _passage("sop_v4", "| Above ₹10 lakh up to ₹50 lakh | AP Controller |")
    (c,) = extract_passage(p, pack, FakeLLM([_claim()]))
    assert c.value["number"] == 1_000_000 and c.value["unit"] == "INR"
    assert c.status == "pending" and c.source_status == "current" and c.authority_rank == 2


def test_quote_verification(pack) -> None:
    p = _passage("sop_v4", "| Above ₹10 lakh up to ₹50 lakh | AP Controller |")
    good, bad = extract_passage(p, pack, FakeLLM([_claim(), _claim(quote="made-up words")]))
    assert good.meta["quote_verified"] is True
    assert bad.meta["quote_verified"] is False


def test_interview_claims_are_practice(pack) -> None:
    p = _passage("interview_1", "Lakshmi: I wait until Tuesday noon.")
    (c,) = extract_passage(
        p,
        pack,
        FakeLLM(
            [
                _claim(
                    topic="missing_grn",
                    parameter="action",
                    kind="rule",
                    value=ExtractedValue(type="text", text="wait until Tuesday noon"),
                    quote="I wait until Tuesday noon",
                )
            ]
        ),
    )
    assert c.kind == "practice"


def test_memo_claims_take_memo_client_scope(pack) -> None:
    p = _passage("cm_inf_02", "an invoice quantity up to 5% above the GRN quantity is accepted")
    (c,) = extract_passage(
        p,
        pack,
        FakeLLM(
            [
                _claim(
                    topic="quantity_tolerance",
                    parameter="pct",
                    client="all",
                    value=ExtractedValue(type="percentage", number=5, unit="percent", text="5%"),
                    quote="up to 5% above the GRN quantity",
                )
            ]
        ),
    )
    assert c.client == "infra" and c.scope["client"] == "infra"
    assert c.value["unit"] == "%"
    assert str(c.source_valid_to) == "2027-03-31"


def test_unknown_vocabulary_is_marked_not_dropped(pack) -> None:
    p = _passage("sop_v4", "text")
    a, b = extract_passage(
        p,
        pack,
        FakeLLM(
            [
                _claim(topic="canteen", parameter="subsidy", proposed_name="canteen subsidy"),
                _claim(topic="approvals", parameter="weekend_rule", proposed_name="weekend rule"),
            ]
        ),
    )
    assert (a.topic, a.parameter) == ("other", "canteen_subsidy")
    assert a.meta["proposed_topic"] == "canteen subsidy"
    assert (b.topic, b.parameter) == ("approvals", "other_weekend_rule")


def test_keys_are_stable_and_distinct(pack) -> None:
    p = _passage("sop_v4", "x")
    first = extract_passage(p, pack, FakeLLM([_claim(), _claim(parameter="cfo_above_lakh")]))
    again = extract_passage(p, pack, FakeLLM([_claim(), _claim(parameter="cfo_above_lakh")]))
    assert [c.key for c in first] == [c.key for c in again]
    assert len({c.key for c in first}) == 2


def test_prompt_uses_pack_vocabulary_and_guidance(pack) -> None:
    fake = FakeLLM([])
    extract_passage(_passage("sop_v4", "body"), pack, fake)
    call = fake.calls[0]
    assert call["model"] == "smart" and call["prompt_version"] == "extract-v1"
    assert "price_tolerance.pct_of_line" in call["prompt"]
    assert "infra (Arvana Infra Projects Ltd)" in build_prompt(_passage("sop_v4", "b"), pack)
    assert "lakh" in system_prompt(pack)  # domain guidance comes from the pack


def test_schema_is_serialisable_for_structured_outputs() -> None:
    schema = ExtractionResult.model_json_schema()
    assert "claims" in schema["properties"]


@pytest.mark.parametrize("verdict", ["same", "different", "narrower"])
def test_llm_comparator_used_only_when_unknown(verdict) -> None:
    calls = []

    def fake(prompt, schema, **kw):
        calls.append(kw)
        return CompareVerdict(verdict=verdict, reason="r")

    from app.graph.schema import ClaimRec

    def rec(text: str, number=None, vtype="text") -> ClaimRec:
        return ClaimRec(
            key=text,
            topic="t",
            parameter="p",
            client="all",
            value={"type": vtype, "number": number, "unit": "%", "text": text},
            kind="rule",
            statement=text,
            source_id="sop_v4",
            source_kind="sop",
            source_status="current",
            authority_rank=2,
            valid_at=None,
        )

    cmp = LLMComparator(structured_fn=fake)
    assert cmp(rec("a", 1, "percentage"), rec("b", 1, "percentage")) == "same"
    assert not calls  # numeric: decided without the LLM
    assert cmp(rec("hold the invoice"), rec("park it")) == verdict
    assert calls and calls[0]["model"] == "fast" and calls[0]["prompt_version"] == "compare-v1"
