"""Answer pipeline pieces without a database: fusion, verification checks, card assembly."""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.answer import card as cards
from app.answer import verify
from app.answer.generate import GenOut, Quote, Sentence
from app.answer.retrieve import rrf
from app.answer.router import RouteOut, route
from app.store.facts import FactRow
from app.store.search import PassageHit

UNITS = {"%": 0.01, "₹": 1.0, "lakh": 100000.0, "crore": 10000000.0, "day": 1.0}


def hit(pid: str, text: str, label: str = "Doc v2", locator: str = "4.2") -> PassageHit:
    return PassageHit(
        id=pid,
        text=text,
        context_header=label,
        locator=locator,
        section_title="Section",
        segment_kind="section",
        speaker=None,
        client_scope="all",
        source_id="s1",
        source_label=label,
        source_title=label,
        doc_type="sop",
        source_status="current",
        dated=date(2026, 4, 1),
        valid_until=None,
        file="doc.docx",
    )


def fact(fid: int, attr: str, value: dict, status: str = "current", label: str = "Doc") -> FactRow:
    return FactRow(
        id=fid,
        origin_key=str(fid),
        subject_id="t",
        attribute=attr,
        value=value,
        scope={},
        statement="",
        kind="rule",
        status=status,
        valid_from=None,
        valid_to=None,
        recorded_at=datetime(2026, 1, 1, tzinfo=UTC),
        retracted_at=None,
        authority_rank=1,
        source_label=label,
    )


def test_rrf_rewards_documents_ranked_high_in_both_lists() -> None:
    fused = rrf([["a", "b", "c"], ["b", "a", "d"]])
    assert [d for d, _ in fused][:2] in (["a", "b"], ["b", "a"])
    assert dict(fused)["d"] < dict(fused)["c"] or dict(fused)["d"] == dict(fused)["c"]


def test_find_quote_exact_ellipsis_and_near_match() -> None:
    p = "The line passes only if the excess is no more than the lower of 1% and 500.  Then post."
    assert verify.find_quote("the excess is no more than the lower of 1%", p)
    assert verify.find_quote("The line passes only if ... the lower of 1% and 500", p)
    assert verify.find_quote(
        "The line passes only if the excess is no more than the lower of 1% and 500!", p
    )
    assert verify.find_quote("Lines always pass when the supplier is trusted", p) is None


def test_numbers_check_allows_evidence_words_and_indian_grouping() -> None:
    allowed = ["Deduct at 2% on 4,80,000.", "limit is five hundred", "Doc v2 §4.2"]
    assert verify.check_numbers("Deduct 2% of ₹480,000 [1].", allowed) == []
    assert verify.check_numbers("The limit is 500 [2].", allowed) == []
    assert verify.check_numbers("The limit is 750 [2].", allowed)
    assert verify.check_numbers("See §4.2 [1].", allowed) == []
    assert verify.word_numbers("five lakh", UNITS) == {500000.0}


def test_values_not_in_force_are_caught_with_their_unit() -> None:
    now = [
        fact(1, "tol.pct", {"type": "percentage", "number": 1, "text": "1%"}),
        fact(2, "tol.cap", {"type": "money", "number": 500, "text": "₹500"}),
    ]
    old = [
        fact(3, "tol.pct", {"type": "percentage", "number": 2, "text": "2%"}, "superseded"),
        fact(4, "tol.cap", {"type": "money", "number": 1000, "text": "₹1,000"}, "superseded"),
    ]
    ok = "The limit is the lower of 1% and ₹500 [1]. Raise it within 2 days [1]."
    assert verify.check_not_in_force(ok, old, now, UNITS, currencies=["₹"]) == []
    bad = "The limit is the lower of 2% and ₹1,000 [1]."
    assert len(verify.check_not_in_force(bad, old, now, UNITS, currencies=["₹"])) == 2
    lakh = [
        fact(
            5, "appr.ctrl", {"type": "money", "number": 1_000_000, "text": "₹10 lakh"}, "superseded"
        )
    ]
    ctrl = [fact(6, "appr.ctrl", {"type": "money", "number": 2_500_000, "text": "₹25 lakh"})]
    assert verify.check_not_in_force("Above ₹10 lakh [1].", lakh, ctrl, UNITS, currencies=["₹"])
    # Not anchored to anything in force (e.g. one fact per code in a list): never flagged.
    other = [fact(7, "codes", {"type": "text", "text": "PRICE_VAR"}, "superseded")]
    assert verify.check_not_in_force("Raise PRICE_VAR [1].", other, now, UNITS) == []


def test_values_from_the_case_or_calculator_are_not_old_rules() -> None:
    now = [
        fact(1, "tol.pct", {"type": "percentage", "number": 1, "text": "1%"}),
        fact(2, "tol.cap", {"type": "money", "number": 500, "text": "₹500"}),
        fact(3, "run.day", {"type": "text", "text": "Tuesday and Friday"}),
    ]
    old = [
        fact(4, "tol.pct", {"type": "percentage", "number": 2, "text": "2%"}, "superseded"),
        fact(5, "tol.cap", {"type": "money", "number": 1000, "text": "₹1,000"}, "superseded"),
        fact(6, "run.day", {"type": "text", "text": "Thursday"}, "superseded"),
    ]
    calc = "Excess on line (₹2 × 500): ₹1,000\nCut-off: 1 pm → Thursday 23 July 2026"
    text = "The excess is ₹1,000, above ₹500 [1]. The cut-off is Thursday 23 July 2026 [1]."
    assert len(verify.check_not_in_force(text, old, now, UNITS, currencies=["₹"])) == 2
    assert verify.check_not_in_force(text, old, now, UNITS, currencies=["₹"], given=[calc]) == []
    # A figure in the calculator output only excuses a value of the same kind: "₹2" there
    # does not let the retired 2% through.
    stale = "The tolerance is 2% [1]."
    assert verify.check_not_in_force(stale, old, now, UNITS, currencies=["₹"], given=[calc])


def test_assemble_numbers_citations_in_order_and_checks_quotes() -> None:
    ev = {"P1": hit("a", "Rule one says pay in 45 days."), "P2": hit("b", "Rule two is here.")}
    gen = GenOut(
        status="answered",
        sentences=[
            Sentence(text="Pay in 45 days.", sources=["P2", "P1"]),
            Sentence(text="Also this.", sources=["P1"]),
        ],
        quotes=[Quote(source="P1", quote="pay in 45 days"), Quote(source="P2", quote="invented")],
    )
    text, cites, cited, problems = cards.assemble(gen, ev)
    assert text == "Pay in 45 days. [1][2] Also this. [2]"
    assert [c["passage_id"] for c in cites] == ["b", "a"] and cited == ["b", "a"]
    assert problems == ["the quote given for P2 does not occur in that passage"]
    assert cites[1]["short_label"] == "Doc v2 §4.2"


def test_processor_never_sees_unverified_text() -> None:
    card = cards.blank(status="unverified", rule={"text": "draft", "citations": [1]})
    card["draft"] = {"rule": card["rule"]}
    shown = cards.view_for(card, "processor")
    assert shown["rule"] == {"text": "", "citations": []} and "draft" not in shown
    assert cards.view_for(card, "owner")["draft"]


def test_route_to_falls_back_to_default_roles() -> None:
    roles = {
        "lead": {"key": "lead", "name": "Team Lead", "default_for": ["process_gap"]},
        "tax": {"key": "tax", "name": "Tax Desk"},
    }
    assert cards.route_to("tax", roles, "x")["role"] == "Tax Desk"
    assert cards.route_to(None, roles, "x")["role"] == "Team Lead"
    assert cards.route_to(None, {}, "x")["role"] == cards.PROCESS_OWNER


def test_router_rejects_unknown_routes_and_low_confidence_calculators() -> None:
    def fake(answer: RouteOut):
        return lambda *a, **k: answer.model_copy()

    calcs = {"calculator:p.price": "price check"}
    r = route("price 5 vs 6", [], calcs, {}, fake(RouteOut(route="weird", confidence=0.9)))
    assert r.route == "lookup"
    r = route(
        "price 5 vs 6", [], calcs, {}, fake(RouteOut(route="calculator:p.price", confidence=0.2))
    )
    assert r.route == "lookup"
    roles = {"tax_desk": {"name": "Tax Desk"}}
    r = route(
        "price 5 vs 6",
        [],
        calcs,
        roles,
        fake(RouteOut(route="calculator:p.price", confidence=0.9, role="ghost")),
    )
    assert r.route == "calculator:p.price" and r.role is None
    named = fake(RouteOut(route="lookup", confidence=0.9, role="Tax desk"))
    assert route("q", [], calcs, roles, named).role == "tax_desk"


def test_calculator_inputs_must_come_from_the_question() -> None:
    from app.answer.pipeline import grounded_inputs

    q = "PO price ₹395 for 500 units; invoice ₹400. Supplier turnover ₹8.9 crore."
    ok = {"po_unit_price": 395, "qty": 500, "inv": 400.0, "aato": 89_000_000, "flag": True}
    assert grounded_inputs(ok, q, UNITS) == []
    assert grounded_inputs({"po_unit_price": 12, "qty": 800}, q, UNITS) == ["12", "800"]
    # 8.9 crore read as 8.9 lakh: the multiplier must be the unit written in the question.
    assert grounded_inputs({"aato": 890_000}, q, UNITS) == ["890000"]


def test_calculator_route_needs_figures() -> None:
    calcs = {"calculator:p.price": "price check"}
    out = route(
        "What is the price tolerance?",
        [],
        calcs,
        {},
        lambda *a, **k: RouteOut(route="calculator:p.price", confidence=0.95),
    )
    assert out.route == "lookup"


def test_induction_ranks_strictly_and_drops_client_named_keys() -> None:
    from app.graph.induce import _complete_ranking, _names_scope, scope_words
    from app.graph.ontology import SourceRank

    r = _complete_ranking(
        [
            SourceRank(doc_type="sop", rank=1),
            SourceRank(doc_type="wi", rank=1),
            SourceRank(doc_type="faq", rank=3),
            SourceRank(doc_type="sop", rank=9),
        ],
        {"sop", "wi", "faq", "email"},
    )
    assert [(x.doc_type, x.rank) for x in r] == [("sop", 1), ("wi", 2), ("faq", 3), ("email", 4)]
    words = scope_words({"all", "Northwind Builders Ltd", "Contoso Pharma"})
    assert _names_scope("client_specific_rules.northwind_qty_cap", words)
    assert _names_scope("tolerance.contoso_cap", words)
    assert not _names_scope("quantity_tolerance.percentage", words)


def test_restatement_needs_no_model_check() -> None:
    ev = ["Annual leave must be requested at least 10 days before the first day of leave."]
    assert verify.restates("Annual leave must be requested at least 10 days before leave.", ev)
    assert not verify.restates("Annual leave must be requested at least 14 days before leave.", ev)
    assert not verify.restates("Annual leave must not be requested 10 days before leave.", ev)

    calls = []

    def fake(prompt, schema, **kw):
        calls.append(prompt)
        return schema(items=[{"sentence": 1, "supported": False, "problem": "x"}])

    problems = verify.support_check(
        [
            ("Annual leave must be requested at least 10 days before leave.", [("1", ev[0])]),
            ("Sick leave is unlimited for everyone.", [("1", ev[0])]),
        ],
        None,
        fake,
    )
    assert len(calls) == 1 and "Sentence 1: Sick leave" in calls[0]
    assert problems and problems[0].startswith("sentence 2 ")


def test_uncited_number_gets_the_evidence_that_states_it() -> None:
    from app.answer.generate import GenOut

    evidence = {
        "P1": hit("a", "Warehouse staff must request leave at least 30 days before leave."),
        "P2": hit("b", "Annual leave must be requested at least 10 days before leave."),
        "P3": hit("c", "Grade L3 carry forward limit is 10 days."),
    }
    gen = GenOut(
        status="answered",
        sentences=[
            {"text": "You need 30 days' notice.", "sources": ["P1"]},
            {
                "text": "This replaces the general 10-day notice for leave requests.",
                "sources": ["P1"],
            },
        ],
    )
    assert cards.attach_number_sources(gen, evidence, ["notice in November?"]) == 1
    assert gen.sentences[0].sources == ["P1"]
    assert gen.sentences[1].sources == ["P1", "P2"]


def test_rule_number_from_its_one_percentage() -> None:
    from app.graph.rules import RuleNotFound, RuleValue

    def rv(text: str) -> RuleValue:
        return RuleValue(
            1,
            "tds.no_pan_rate",
            None,
            {"text": text},
            "",
            "current",
            None,
            None,
            None,
            None,
            None,
            None,
        )

    assert rv("20% or the applicable rate, whichever is higher").number == 20.0
    try:
        _ = rv("1% for individuals, 2% for others").number
        raise AssertionError("two percentages must not pick one")
    except RuleNotFound:
        pass


def test_params_guards_need_the_question_to_say_so() -> None:
    from plugins.ap.calc.params import ScenarioParams, extract_params

    def fake(out: dict):
        return lambda *a, **k: ScenarioParams.model_validate(out)

    tds = {
        "family": "tds",
        "tds": {
            "nature": "professional",
            "reverse_charge_service": False,
            "taxable_value": {"amount": 100, "unit": "INR"},
            "pan_available": False,
        },
    }
    assert extract_params("Legal advice, ₹100. What TDS?", [], fake(tds)).tds.pan_available
    p = extract_params("Legal advice; the supplier has no PAN.", [], fake(tds))
    assert not p.tds.pan_available


def test_stated_agreed_term_counts_as_written_unless_said_otherwise() -> None:
    from plugins.ap.calc.params import ScenarioParams, extract_params

    out = {
        "family": "msme",
        "msme": {
            "category": "small",
            "acceptance_date": "2026-04-01",
            "agreed_term_days": 60,
            "written_agreement": False,
        },
    }

    def fake(*a, **k):
        return ScenarioParams.model_validate(out)

    p = extract_params("Small enterprise; agreed payment term 60 days.", [], fake)
    assert p.msme.written_agreement
    p = extract_params("Small enterprise; term of 60 days, no written agreement.", [], fake)
    assert not p.msme.written_agreement


def test_a_list_written_as_one_phrase_is_split_into_items() -> None:
    from app.graph.rules import RuleValue

    def rv(value: dict) -> RuleValue:
        return RuleValue(1, "a", None, value, "", "current", None, None, None, None, None, None)

    assert rv({"type": "enum", "text": "Tuesday and Friday"}).items == ["Tuesday", "Friday"]
    assert rv({"type": "list", "text": "cement, steel & sand"}).items == ["cement", "steel", "sand"]
    assert rv({"type": "enum", "text": "Thursday"}).items == []
    assert rv({"type": "text", "text": "Terms and conditions"}).items == []
    assert rv({"type": "enum", "text": "x", "items": ["A", "B"]}).items == ["A", "B"]


def test_a_date_from_the_passage_tags_is_a_cited_number() -> None:
    from app.answer.generate import evidence_tags

    h = hit("a", "Up to 5% above the GRN quantity is accepted.")
    h.valid_until = date(2027, 3, 31)
    text = "Up to 5% is accepted until 31 March 2027 [1]."
    assert verify.check_numbers(text, [h.text])  # the body alone does not carry the date
    assert verify.check_numbers(text, [h.text, evidence_tags(h, None)]) == []
