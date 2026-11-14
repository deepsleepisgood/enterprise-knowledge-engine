"""Retrieval reads: passage full-text and vector search, entity linking, embedding backfill.

Passages are filtered to what was in force: live, not stale or draft, valid on the day asked
(`as_of`, default today), general or in the asker's client scope. Records (spreadsheet rows) and
parent passages are not retrieved; their leaf passages carry the text.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import PurePath
from typing import Any

from sqlalchemy import func, or_, select, text, update
from sqlalchemy.orm import Session

from app.store.base import norm_name, tenant
from app.store.models import Entity, EntityAlias, Episode, Fact, Passage, Source

CURRENT_SOURCES = ["current", "provisional", "record"]
THEN_SOURCES = ["current", "superseded", "provisional", "record"]


@dataclass
class PassageHit:
    id: str
    text: str
    context_header: str
    locator: str
    section_title: str | None
    segment_kind: str
    speaker: str | None
    client_scope: str
    source_id: str
    source_label: str
    source_title: str
    doc_type: str
    source_status: str
    dated: date | None
    valid_until: date | None
    file: str
    score: float = 0.0

    @property
    def label(self) -> str:
        """'SOP v4.0 §4.2', 'Interview 1 [02:30]': the source label plus the locator."""
        loc = (self.locator or "").strip()
        if not loc or loc in self.source_label:
            return self.source_label
        if loc.startswith(self.source_label) or self.source_label in loc:
            return loc
        if loc[:1].isdigit():
            return f"{self.source_label} §{loc}"
        return f"{self.source_label} {loc}"


def _filters(
    client: str | None, as_of: date | None, today: date, known_at: datetime | None = None
) -> list[Any]:
    day = as_of or today
    out: list[Any] = [
        Passage.tenant_id == tenant(),
        Passage.segment_kind != "record",
        Passage.meta["leaf"].astext == "true",
        or_(Source.dated.is_(None), Source.dated <= day),
    ]
    if known_at is None:
        out += [
            or_(Source.valid_until.is_(None), Source.valid_until >= day),
            Passage.retired_at.is_(None),
            Source.status.in_(THEN_SOURCES if as_of else CURRENT_SOURCES),
        ]
    else:
        # What the engine had at that moment: sources received by then. A source's status and
        # end date are today's (a later version may have closed it since), so the facts, which
        # keep both clocks, decide what was in force then; here any once-valid source passes.
        out += [
            Source.created_at <= known_at,
            or_(Passage.retired_at.is_(None), Passage.retired_at > known_at),
            Source.status.in_(THEN_SOURCES),
        ]
    if client:
        out.append(Passage.client_scope.in_(["all", client]))
    return out


def _tsquery_text(session: Session, question: str) -> str:
    """OR of the question's English lexemes, quoted for to_tsquery('simple', ...)."""
    return (
        session.scalar(
            text(
                "SELECT array_to_string(array(SELECT quote_literal(x) FROM "
                "unnest(tsvector_to_array(to_tsvector('english', :t))) x), ' | ')"
            ),
            {"t": question},
        )
        or ""
    )


def fulltext(
    session: Session,
    question: str,
    k: int,
    client: str | None = None,
    as_of: date | None = None,
    today: date | None = None,
    known_at: datetime | None = None,
) -> list[tuple[str, float]]:
    qs = _tsquery_text(session, question)
    if not qs:
        return []
    tsq = func.to_tsquery("simple", qs)
    rank = func.ts_rank_cd(Passage.tsv, tsq)
    q = (
        select(Passage.id, rank)
        .join(Source, Source.id == Passage.source_id)
        .where(*_filters(client, as_of, today or date.today(), known_at), Passage.tsv.op("@@")(tsq))
        .order_by(rank.desc(), Passage.id)
        .limit(k)
    )
    return [(pid, float(r)) for pid, r in session.execute(q)]


def vector(
    session: Session,
    vec: list[float],
    k: int,
    client: str | None = None,
    as_of: date | None = None,
    today: date | None = None,
    known_at: datetime | None = None,
) -> list[tuple[str, float]]:
    dist = Passage.embedding.cosine_distance(vec)
    q = (
        select(Passage.id, 1 - dist)
        .join(Source, Source.id == Passage.source_id)
        .where(
            *_filters(client, as_of, today or date.today(), known_at),
            Passage.embedding.is_not(None),
        )
        .order_by(dist, Passage.id)
        .limit(k)
    )
    return [(pid, float(s)) for pid, s in session.execute(q)]


def hydrate(
    session: Session, ids: list[str], known_at: datetime | None = None
) -> dict[str, PassageHit]:
    """Passages with their source details (file, label, type, status, validity). With `known_at`,
    a source whose newer version arrived after that moment is shown as it was then: current, with
    no end date set by the newer version."""
    if not ids:
        return {}
    q = (
        select(Passage, Source, Episode.source_uri)
        .join(Source, Source.id == Passage.source_id)
        .join(Episode, Episode.id == Passage.episode_id)
        .where(Passage.tenant_id == tenant(), Passage.id.in_(ids))
    )
    out = {}
    for p, s, uri in session.execute(q):
        out[p.id] = PassageHit(
            id=p.id,
            text=p.text,
            context_header=p.context_header,
            locator=p.locator,
            section_title=p.section_title,
            segment_kind=p.segment_kind,
            speaker=p.speaker,
            client_scope=p.client_scope,
            source_id=s.id,
            source_label=s.short_label,
            source_title=s.title,
            doc_type=s.doc_type,
            source_status=s.status,
            dated=s.dated,
            valid_until=s.valid_until,
            file=PurePath(uri).name if uri else s.title,
        )
    if known_at is not None and out:
        _as_known(session, out, known_at)
    return out


def _as_known(session: Session, hits: dict[str, PassageHit], known_at: datetime) -> None:
    olds = {h.source_id for h in hits.values() if h.source_status == "superseded"}
    if not olds:
        return
    later = {
        old_id: dated
        for old_id, created, dated in session.execute(
            select(Source.supersedes_source_id, Source.created_at, Source.dated).where(
                Source.tenant_id == tenant(), Source.supersedes_source_id.in_(olds)
            )
        )
        if created > known_at
    }
    for h in hits.values():
        if h.source_id in later:
            dated = later[h.source_id]
            h.source_status = "current"
            if dated is not None and h.valid_until == dated - timedelta(days=1):
                h.valid_until = None


def procedure_steps(session: Session, source_id: str, procedure: str) -> list[str]:
    """Passage ids of every step of one procedure (locators "<procedure>, step <n>"), in
    document order."""
    q = (
        select(Passage.id)
        .where(
            Passage.tenant_id == tenant(),
            Passage.source_id == source_id,
            Passage.segment_kind == "step",
            Passage.locator.startswith(f"{procedure}, step ", autoescape=True),
        )
        .order_by(Passage.ordinal)
    )
    return list(session.scalars(q))


# ---------------------------------------------------------------- entity linking


def entities_named_in(session: Session, question: str) -> list[tuple[str, str, str]]:
    """(id, type, name) of entities whose alias occurs in the question as whole words."""
    qn = f" {norm_name(question)} "
    rows = session.execute(
        select(Entity.id, Entity.type, Entity.name, EntityAlias.alias_norm)
        .join(EntityAlias, EntityAlias.entity_id == Entity.id)
        .where(
            Entity.tenant_id == tenant(),
            Entity.merged_into.is_(None),
            func.length(EntityAlias.alias_norm) >= 3,
            func.strpos(qn, EntityAlias.alias_norm) > 0,
        )
    ).all()
    seen: dict[str, tuple[str, str, str]] = {}
    for eid, typ, name, alias in rows:
        if f" {alias} " in qn:
            seen.setdefault(eid, (eid, typ, name))
    return list(seen.values())


def similar_entities(
    session: Session, vec: list[float], k: int = 5, min_sim: float = 0.0
) -> list[tuple[str, str, str, float]]:
    dist = Entity.embedding.cosine_distance(vec)
    q = (
        select(Entity.id, Entity.type, Entity.name, 1 - dist)
        .where(
            Entity.tenant_id == tenant(),
            Entity.merged_into.is_(None),
            Entity.embedding.is_not(None),
        )
        .order_by(dist)
        .limit(k)
    )
    return [(i, t, n, float(s)) for i, t, n, s in session.execute(q) if s >= min_sim]


# ---------------------------------------------------------------- embedding index


def passages_without_embedding(session: Session, limit: int = 2000) -> list[tuple[str, str]]:
    q = (
        select(Passage.id, Passage.context_header, Passage.text)
        .where(
            Passage.tenant_id == tenant(),
            Passage.retired_at.is_(None),
            Passage.embedding.is_(None),
            Passage.segment_kind != "record",
            Passage.meta["leaf"].astext == "true",
        )
        .order_by(Passage.id)
        .limit(limit)
    )
    return [(i, f"{h}\n{t}") for i, h, t in session.execute(q)]


def facts_without_embedding(session: Session, limit: int = 5000) -> list[tuple[int, str]]:
    q = (
        select(Fact.id, Fact.statement)
        .where(Fact.tenant_id == tenant(), Fact.retracted_at.is_(None), Fact.embedding.is_(None))
        .order_by(Fact.id)
        .limit(limit)
    )
    return [(i, t) for i, t in session.execute(q)]


def set_fact_embeddings(session: Session, vectors: dict[int, list[float]]) -> None:
    """Fill the derived `embedding` index column. It is not part of the fact's content, so
    setting it is not a change of belief and needs no new version."""
    for fid, vec in vectors.items():
        session.execute(
            update(Fact).where(Fact.tenant_id == tenant(), Fact.id == fid).values(embedding=vec)
        )


def entities_without_embedding(session: Session, limit: int = 5000) -> list[tuple[str, str]]:
    q = (
        select(Entity.id, Entity.type, Entity.name)
        .where(
            Entity.tenant_id == tenant(),
            Entity.merged_into.is_(None),
            Entity.embedding.is_(None),
        )
        .order_by(Entity.id)
        .limit(limit)
    )
    return [(i, f"{n} ({t})") for i, t, n in session.execute(q)]


def set_entity_embeddings(session: Session, vectors: dict[str, list[float]]) -> None:
    for eid, vec in vectors.items():
        session.execute(
            update(Entity)
            .where(Entity.tenant_id == tenant(), Entity.id == eid)
            .values(embedding=vec)
        )
