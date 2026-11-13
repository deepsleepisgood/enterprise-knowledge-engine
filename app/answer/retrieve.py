"""Retrieval: hybrid passage search plus graph context (BUILD_PLAN Phase 4).

Passages: full-text top k + vector top k -> reciprocal rank fusion -> cross-encoder rerank -> keep
the best few. Graph context: entities named in (or close to) the question, their facts in force on
the day asked, one more hop along object entities, and the facts extracted from the kept passages,
ranked by similarity to the question. Practice facts are returned separately (expert tips), never
as evidence for a rule. Superseded facts are not fetched here; the card asks for them separately.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.graph.rows import ORIGIN as ROW_ORIGIN
from app.graph.rules import CURRENT, IN_FORCE_THEN
from app.store import facts as fstore
from app.store import search
from app.store.base import day_start
from app.store.facts import FactRow
from app.store.search import PassageHit

EmbedFn = Callable[[list[str]], list[list[float]]]
RerankFn = Callable[[str, list[str]], list[float]]
RRF_K = 60
EVIDENCE_KINDS = ["rule", "attribute", "definition", "procedure"]
ENTITY_MIN_SIM = 0.78
TIP_MIN_SIM = 0.62
NAMED_PRACTICE_MAX = 4


@dataclass
class Retrieved:
    passages: list[PassageHit]
    top_score: float | None
    scorer: str  # "rerank" or "vector"
    facts: list[FactRow] = field(default_factory=list)
    tips: list[tuple[FactRow, float]] = field(default_factory=list)
    entities: list[tuple[str, str, str]] = field(default_factory=list)
    vec: list[float] = field(default_factory=list)
    # Notes read from data rows about an entity the question names outright (by alias). Search
    # never returns data rows, so without this they could not be cited; they are evidence tagged
    # as practice. Practice from documents is found by search as before and is not added here.
    named_practice: list[FactRow] = field(default_factory=list)


def rrf(rankings: list[list[str]], k: int = RRF_K) -> list[tuple[str, float]]:
    """Reciprocal rank fusion: score(d) = sum 1 / (k + rank)."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc in enumerate(ranking, start=1):
            scores[doc] = scores.get(doc, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))


def link_entities(
    session: Session,
    question: str,
    vec: list[float],
    named: list[tuple[str, str, str]] | None = None,
) -> list[tuple[str, str, str]]:
    """Entities named in the question (alias match), then the closest by embedding."""
    named = search.entities_named_in(session, question) if named is None else named
    out = {e[0]: e for e in named}
    for eid, typ, name, _ in search.similar_entities(session, vec, k=5, min_sim=ENTITY_MIN_SIM):
        out.setdefault(eid, (eid, typ, name))
    return list(out.values())[:8]


def _in_scope(f: FactRow, client: str | None) -> bool:
    c = (f.scope or {}).get("client")
    return not c or c == "all" or client is None or c == client


def _valid_on(f: FactRow, day: date) -> bool:
    t = day_start(day)
    return (f.valid_from is None or f.valid_from <= t) and (f.valid_to is None or t < f.valid_to)


def graph_context(
    session: Session,
    question_vec: list[float],
    entity_ids: list[str],
    passage_ids: list[str],
    client: str | None,
    as_of: date | None,
    known_at: datetime | None,
    today: date,
    cap: int,
) -> tuple[list[FactRow], list[tuple[FactRow, float]]]:
    day = as_of or today
    statuses = IN_FORCE_THEN if as_of else CURRENT
    first = fstore.facts_touching(
        session, entity_ids, valid_on=day, known_at=known_at, statuses=statuses
    )
    hop = sorted({f.object_id for f in first if f.object_id and f.object_id not in entity_ids})
    second = fstore.facts_touching(
        session, hop[:10], valid_on=day, known_at=known_at, statuses=statuses
    )
    from_passages = (
        [
            f
            for f in fstore.live_for_passages(session, passage_ids)
            if f.status in statuses and _valid_on(f, day)
        ]
        if known_at is None
        else []
    )
    boost = {f.id for f in from_passages}
    pool = {f.id: f for f in [*first, *second] if _in_scope(f, client)}
    labelled = fstore.by_ids(session, [f.id for f in from_passages if _in_scope(f, client)])
    pool.update(labelled)
    sims = fstore.similarity(session, list(pool), question_vec)
    ranked = sorted(
        pool.values(), key=lambda f: -(sims.get(f.id, 0.0) + (0.05 if f.id in boost else 0.0))
    )
    evidence = [f for f in ranked if f.kind in EVIDENCE_KINDS][:cap]
    tips = {f.id: (f, sims.get(f.id, 0.0)) for f in ranked if f.kind == "practice"}
    for f, s in fstore.nearest(
        session,
        question_vec,
        5,
        valid_on=day,
        known_at=known_at,
        statuses=["current"],
        kinds=["practice"],
    ):
        if _in_scope(f, client):
            tips.setdefault(f.id, (f, s))
    good_tips = sorted((t for t in tips.values() if t[1] >= TIP_MIN_SIM), key=lambda t: -t[1])
    return evidence, good_tips[:3]


def retrieve(
    session: Session,
    question: str,
    client: str | None = None,
    as_of: date | None = None,
    known_at: datetime | None = None,
    today: date | None = None,
    embed_fn: EmbedFn | None = None,
    rerank_fn: RerankFn | None = None,
) -> Retrieved:
    cfg = get_settings()
    today = today or date.today()
    if embed_fn is None:
        from app.core.embed import embed as embed_fn
    if rerank_fn is None:
        from app.core import rerank as rr

        rerank_fn = rr.rerank if rr.enabled() else None
    vec = embed_fn([question])[0]
    ft = search.fulltext(session, question, cfg.retrieve_k, client, as_of, today, known_at)
    vv = search.vector(session, vec, cfg.retrieve_k, client, as_of, today, known_at)
    vsim = dict(vv)
    fused = rrf([[i for i, _ in ft], [i for i, _ in vv]])[: cfg.retrieve_k]
    hits = search.hydrate(session, [i for i, _ in fused], known_at)
    cands = [hits[i] for i, _ in fused if i in hits]
    if rerank_fn is not None and cands:
        scores = rerank_fn(question, [f"{h.context_header}\n{h.text}"[:2000] for h in cands])
        for h, sc in zip(cands, scores, strict=True):
            h.score = sc
        cands.sort(key=lambda h: -h.score)
        scorer = "rerank"
    else:
        for h in cands:
            h.score = vsim.get(h.id, 0.0)
        scorer = "vector"  # keep RRF order; the gate reads the best vector similarity
    kept = cands[: cfg.answer_passages]
    top = (
        max((h.score for h in cands), default=None)
        if scorer == "rerank"
        else (max(vsim.values(), default=None))
    )
    named = search.entities_named_in(session, question)
    entities = link_entities(session, question, vec, named)
    facts, tips = graph_context(
        session,
        vec,
        [e[0] for e in entities],
        [h.id for h in kept],
        client,
        as_of,
        known_at,
        today,
        cfg.graph_facts,
    )
    named_ids = {e[0] for e in named}
    day = as_of or today
    named_practice = [
        f
        for f in fstore.facts_touching(
            session,
            sorted(named_ids),
            valid_on=day,
            known_at=known_at,
            statuses=IN_FORCE_THEN if as_of else CURRENT,
            kinds=["practice"],
        )
        if f.subject_id in named_ids
        and f.origin_key.startswith(ROW_ORIGIN)
        and _in_scope(f, client)
    ][:NAMED_PRACTICE_MAX]
    return Retrieved(kept, top, scorer, facts, tips, entities, vec, named_practice)
