"""ask(): route -> retrieve -> calculate -> generate -> verify -> card -> log.

Grounding: out-of-scope questions never reach generation; a weak retrieval score abstains;
generation is closed-book; the verifier withholds anything it cannot confirm (after one retry the
card is `unverified` and processors get the not-covered card); numbers come from calculators and
graph values; every answer is logged with its citations and verifier result.
"""

from __future__ import annotations

import time
from datetime import date, datetime
from typing import Any

from app.answer import card as cards
from app.answer import verify
from app.answer.generate import CalcView, GenOut, evidence_ids, generate
from app.answer.retrieve import EmbedFn, RerankFn, retrieve
from app.answer.router import route
from app.core.config import get_settings
from app.core.db import session_scope
from app.graph.pipeline import active_ontology
from app.graph.rules import RuleNotFound, canonical_client
from app.plugins import calculate as calc_mod
from app.plugins import registry
from app.store import answers as astore
from app.store import entities as estore
from app.store import facts as fstore
from app.store import kb, search

MAX_EVIDENCE = 12
UNSUPPORTED = "The documents in the knowledge base do not cover this."


def _default_structured() -> Any:
    """The gateway's structured call; reasoning off on the answer path unless configured."""
    from functools import partial

    from app.core.llm import structured

    return structured if get_settings().answer_thinking else partial(structured, thinking=False)


def grounded_inputs(
    inputs: dict[str, Any],
    question: str,
    units: dict[str, float],
    currencies: list[str] | None = None,
) -> list[str]:
    """Numeric calculator inputs that do not come from the question: a number as written, or an
    amount converted with the unit written next to it ("8.9 million" may become 8,900,000, never
    890,000). A calculator never runs on figures the asker did not give."""
    from app.answer.verify import mentions, numbers

    given = numbers(question) | mentions(question, units, currencies)["money"]

    def leaves(x: Any) -> list[float]:
        if isinstance(x, bool) or x is None:
            return []
        if isinstance(x, (int, float)):
            return [float(x)]
        if isinstance(x, dict):
            return [v for item in x.values() for v in leaves(item)]
        if isinstance(x, (list, tuple)):
            return [v for item in x for v in leaves(item)]
        return []

    def ok(v: float) -> bool:
        return any(abs(v - g) < 1e-6 * max(1.0, abs(v)) for g in given)

    return [f"{v:g}" for v in leaves(inputs) if not ok(v)]


def _with_model(structured: Any, model: str) -> Any:
    """The same structured call, pinned to `model` (the plug-in asks for its own model)."""

    def call(prompt: str, schema: Any, **kw: Any) -> Any:
        return structured(prompt, schema, **{**kw, "model": model})

    return call


def _calc_view(route_key: str, res: Any) -> CalcView:
    return CalcView(
        route=route_key,
        decision=res.decision,
        exception_code=res.exception_code,
        next_owner=res.next_owner,
        working=[(w.label, w.value) for w in res.working],
        notes=list(res.notes or []),
    )


def _calc_text(c: CalcView | None) -> str | None:
    if c is None:
        return None
    rows = "\n".join(f"{k}: {v}" for k, v in c.working)
    return f"decision: {c.decision}\nexception: {c.exception_code}\n{rows}"


def _merge_older(older: list[dict], conflicting: list[dict], limit: int = 4) -> list[dict]:
    """Older versions first, then sources the conflict scan found disagreeing (no repeats)."""
    out, seen = [], set()
    for o in [*older, *conflicting]:
        key = (o.get("file"), str(o.get("older_value", "")).lower())
        if key not in seen:
            seen.add(key)
            out.append(o)
    return out[:limit]


def ask(
    question: str,
    client: str | None = None,
    as_of: date | None = None,
    known_at: datetime | None = None,
    user_id: str = "anonymous",
    viewer: str = "processor",
    today: date | None = None,
    structured_fn: Any = None,
    embed_fn: EmbedFn | None = None,
    rerank_fn: RerankFn | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    cfg = get_settings()
    structured = structured_fn or _default_structured()
    today = today or date.today()
    roles = registry.roles()
    calculators = calc_mod.routes()
    diag: dict[str, Any] = {}

    with session_scope() as s:
        onto = active_ontology(s)
        if onto is None:
            raise RuntimeError("no frozen schema: build the graph first")
        kbv = kb.current_kb_version(s)
        clients = [e.name for e in estore.list_entities(s, "client")]

        r = route(question, clients, calculators, roles, structured)
        asked = client if client and client != "all" else r.client
        client_name = canonical_client(s, asked) if asked else None
        diag["router"] = r.model_dump()
        base = cards.blank(
            kb_version=kbv,
            as_of=as_of.isoformat() if as_of else None,
            client=client_name,
            route=r.route,
        )

        def finish(card: dict[str, Any], facts: list[int], passages: list[str]) -> dict[str, Any]:
            card["latency_ms"] = int((time.perf_counter() - started) * 1000)
            card["diagnostics"] = diag
            aid = astore.log_answer(
                s,
                user_id=user_id,
                question=question,
                client=client_name,
                as_of=as_of,
                kb_version=kbv,
                route=card["route"],
                card=card,
                cited_fact_ids=facts,
                cited_passage_ids=passages,
                latency_ms=card["latency_ms"],
            )
            card["answer_id"] = str(aid)
            astore.update_card(s, aid, card)
            return cards.view_for(card, viewer)

        if r.route == "out_of_scope":
            base["route_to"] = cards.route_to(
                r.role, roles, f"Outside what the knowledge base covers ({r.out_of_scope_reason})."
            )
            return finish(base, [], [])

        got = retrieve(s, question, client_name, as_of, known_at, today, embed_fn, rerank_fn)
        base["entities"] = [{"id": i, "name": n, "type": t} for i, t, n in got.entities]
        diag["retrieval"] = {
            "scorer": got.scorer,
            "top_score": got.top_score,
            "passages": [(p.label, p.id, round(p.score, 3)) for p in got.passages],
            "facts": [f.id for f in got.facts],
        }

        calc = None
        res = None
        if r.route.startswith("calculator:"):
            plugin = r.route.split(":", 1)[1].split(".", 1)[0]
            try:
                prep = calc_mod.inputs_for(
                    plugin, question, clients, onto, _with_model(structured, cfg.router_model)
                )
                if prep is not None:
                    family, inputs = prep
                    stray = grounded_inputs(
                        inputs, question, onto.units, [onto.base_currency or ""]
                    )
                    if stray:
                        raise ValueError(f"calculator inputs not in the question: {stray}")
                    if client_name and not inputs.get("client"):
                        inputs["client"] = client_name
                    res = calc_mod.calculate(
                        s, onto, plugin, family, inputs, today=today, as_of=as_of
                    )
                    calc = _calc_view(f"calculator:{plugin}.{family}", res)
                    base["route"] = calc.route
                    diag["calculator"] = {
                        "family": family,
                        "inputs": inputs,
                        "passed": res.passed,
                        "decision": res.decision,
                        "exception_code": res.exception_code,
                        "result": res.result,
                    }
            except (RuleNotFound, ValueError) as exc:
                diag["calculator_error"] = f"{type(exc).__name__}: {exc}"
            if calc is None:
                base["route"] = "lookup"

        threshold = cfg.abstain_rerank_score if got.scorer == "rerank" else cfg.abstain_vector_score
        if calc is None and (got.top_score is None or got.top_score < threshold):
            base["route_to"] = cards.route_to(r.role, roles, UNSUPPORTED)
            diag["abstained"] = "retrieval score below threshold"
            return finish(base, [], [])

        # Evidence: calculator rule sources first, then reranked passages, then fact sources.
        calc_pids = [c.passage_id for c in (res.citations if res else []) if c.passage_id]
        fact_pids = [f.passage_id for f in got.facts if f.passage_id]
        order = list(dict.fromkeys([*calc_pids, *[p.id for p in got.passages], *fact_pids]))
        hits = search.hydrate(s, order[:MAX_EVIDENCE])
        evidence = evidence_ids([hits[i] for i in order[:MAX_EVIDENCE] if i in hits])

        failures: list[str] | None = None
        gen: GenOut | None = None
        verified = False
        rule_text, cites, cited = "", [], []
        problems: list[str] = []
        attempts: list[list[str]] = []
        in_force: list = []
        not_in_force: list = []
        for _attempt in range(2):
            gen = generate(
                question, client_name, as_of, evidence, got.facts, calc, structured, failures
            )
            if gen.status == "unsupported":
                break
            given = [question, _calc_text(calc) or "", as_of.isoformat() if as_of else ""]
            given.append(str(res.result) if res is not None else "")
            if added := cards.attach_number_sources(gen, evidence, given):
                diag["citations_added"] = diag.get("citations_added", 0) + added
            rule_text, cites, cited, problems = cards.assemble(gen, evidence)
            cited_hits = [h for h in evidence.values() if h.id in cited]
            allowed = [h.text for h in cited_hits]
            allowed += [f"{h.label} {h.locator} {h.section_title or ''}" for h in cited_hits]
            allowed += [question, _calc_text(calc) or "", as_of.isoformat() if as_of else ""]
            if res is not None:
                allowed.append(str(res.result))
            problems += verify.check_numbers(rule_text, allowed, onto.units)
            attrs = sorted(
                {f.attribute for f in fstore.live_for_passages(s, cited)}
                | {c.attribute for c in (res.citations if res else [])}
            )
            in_force, not_in_force = cards.force_split(s, attrs, client_name, as_of, today)
            problems += verify.check_not_in_force(
                rule_text,
                not_in_force,
                in_force,
                onto.units,
                when=f"in force on {as_of}" if as_of else "current",
                currencies=[onto.base_currency or ""],
                given=given,
            )
            if not problems:
                sentences = [
                    (sent.text, [(evidence[x].label, evidence[x].text) for x in sent.sources])
                    for sent in gen.sentences
                ]
                problems = verify.support_check(sentences, _calc_text(calc), structured, question)
            if not problems:
                verified = True
                break
            attempts.append(problems)
            failures = problems
        diag["verifier"] = {"verified": verified, "problems": problems, "attempts": attempts}

        assert gen is not None
        if gen.status == "unsupported":
            base["route_to"] = cards.route_to(r.role, roles, gen.reason or UNSUPPORTED)
            if calc is not None:  # deterministic output stands even if the prose abstains
                base["working"] = [{"label": k, "value": v} for k, v in calc.working]
            return finish(base, [], [])

        cited_set = set(cited)
        cited_keys: dict[tuple[str, str], int] = {}
        for f in fstore.live_for_passages(s, cited):
            pos = cited.index(f.passage_id) if f.passage_id in cited else 99
            key = (f.subject_id, f.attribute)
            cited_keys[key] = min(pos, cited_keys.get(key, 99))
        for c in res.citations if res else []:
            for f in in_force:
                if f.id == c.fact_id:
                    cited_keys.setdefault((f.subject_id, f.attribute), 0)
        cited_facts = [f.id for f in in_force if f.passage_id in cited_set]
        cited_facts += [c.fact_id for c in (res.citations if res else [])]
        card = dict(base)
        card.update(
            rule={"text": rule_text, "citations": cites},
            working=[{"label": k, "value": v} for k, v in calc.working] if calc else None,
            decision=(calc.decision if calc else gen.decision),
            exception_code=calc.exception_code if calc else None,
            next_owner=calc.next_owner if calc else None,
            older_sources=_merge_older(
                cards.older_sources(
                    s, onto, in_force, not_in_force, as_of, today, cited_keys=cited_keys
                ),
                [] if as_of else cards.conflicting_sources(s, sorted(set(cited_facts))),
            ),
            expert_tip=cards.expert_tip(
                s,
                got.tips,
                as_of or today,
                {r.doc_type for r in onto.source_ranking if r.practice},
                [(p.id, p.score) for p in got.passages],
            ),
            related=[q for q in gen.related if q.strip()][:4],
        )
        if as_of:
            card["superseded_since"] = cards.superseded_since(in_force, set(cited_facts), today)
        provisional = any(
            h.source_status == "provisional" for h in evidence.values() if h.id in cited_set
        ) or any(f.status == "provisional" for f in in_force if f.id in set(cited_facts))
        if not verified:
            card["status"] = "unverified"
            card["draft"] = {"rule": card["rule"], "problems": problems}
            card["route_to"] = cards.route_to(
                r.role, roles, "The answer could not be verified against the documents."
            )
        elif gen.status == "needs_specialist":
            card["status"] = "needs_specialist"
            card["route_to"] = cards.route_to(r.role, roles, gen.reason or "Needs a specialist.")
        else:
            card["status"] = "provisional" if provisional else "answered"
        return finish(card, sorted(set(cited_facts)), cited)
