"""Bitemporal fact rows. All fact reads and writes go through here.

Valid time: [valid_from, valid_to). Transaction time: [recorded_at, retracted_at).
A row is never changed after insert except for closing `retracted_at`. A change of belief about a
fact (status, validity) retracts the live row and inserts a new version with the same origin_key.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import date, datetime
from typing import Any

from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.orm import Session

from app.store.base import day_start, tenant, utcnow
from app.store.models import Entity, Fact, Passage, Source


@dataclass
class FactRow:
    """A fact version as callers see it (no ORM objects leave the store)."""

    id: int
    origin_key: str
    subject_id: str
    attribute: str
    value: dict[str, Any]
    scope: dict[str, Any]
    statement: str
    kind: str
    status: str
    valid_from: datetime | None
    valid_to: datetime | None
    recorded_at: datetime
    retracted_at: datetime | None
    authority_rank: int
    object_id: str | None = None
    condition: str | None = None
    quote: str | None = None
    passage_id: str | None = None
    episode_id: str | None = None
    source_id: str | None = None
    supersedes_id: int | None = None
    confidence: float | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    subject_name: str | None = None
    source_label: str | None = None
    locator: str | None = None


_FIELDS = [
    f.name for f in fields(FactRow) if f.name not in ("subject_name", "source_label", "locator")
]


def _row(f: Fact, subject_name=None, source_label=None, locator=None) -> FactRow:
    return FactRow(
        **{k: getattr(f, k) for k in _FIELDS},
        subject_name=subject_name,
        source_label=source_label,
        locator=locator,
    )


@dataclass
class NewFact:
    origin_key: str
    subject_id: str
    attribute: str
    value: dict[str, Any]
    statement: str
    kind: str
    status: str
    scope: dict[str, Any] = field(default_factory=dict)
    object_id: str | None = None
    condition: str | None = None
    quote: str | None = None
    passage_id: str | None = None
    episode_id: str | None = None
    source_id: str | None = None
    authority_rank: int = 99
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    supersedes_id: int | None = None
    confidence: float | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    embedding: list[float] | None = None


def insert(session: Session, nf: NewFact, at: datetime | None = None) -> int:
    f = Fact(tenant_id=tenant(), recorded_at=at or utcnow(), **nf.__dict__)
    session.add(f)
    session.flush()
    return f.id


def retract(session: Session, fact_id: int, at: datetime | None = None) -> None:
    session.execute(
        update(Fact)
        .where(Fact.id == fact_id, Fact.retracted_at.is_(None))
        .values(retracted_at=at or utcnow())
    )


def revise(session: Session, fact_id: int, at: datetime | None = None, **changes: Any) -> int:
    """Retract the live row and insert a new version carrying `changes`. Returns the new id."""
    at = at or utcnow()
    old = session.get(Fact, fact_id)
    if old is None or old.retracted_at is not None:
        raise ValueError(f"fact {fact_id} is not live")
    data = {k: getattr(old, k) for k in _FIELDS if k not in ("id", "recorded_at", "retracted_at")}
    data["embedding"] = old.embedding
    data.update(changes)
    retract(session, fact_id, at)
    session.flush()
    new = Fact(tenant_id=old.tenant_id, recorded_at=at, **data)
    session.add(new)
    session.flush()
    return new.id


def _time_filters(valid_on: date | datetime | None, known_at: datetime | None) -> list[Any]:
    out: list[Any] = []
    if known_at is None:
        out.append(Fact.retracted_at.is_(None))
    else:
        out.append(
            func.tstzrange(Fact.recorded_at, Fact.retracted_at).op("@>")(day_start(known_at))
        )
    if valid_on is not None:
        out.append(func.tstzrange(Fact.valid_from, Fact.valid_to).op("@>")(day_start(valid_on)))
    return out


def get_facts(
    session: Session,
    subject_id: str | None = None,
    attribute: str | list[str] | None = None,
    scope: dict[str, Any] | None = None,
    valid_on: date | datetime | None = None,
    known_at: datetime | None = None,
    statuses: list[str] | None = None,
    kinds: list[str] | None = None,
) -> list[FactRow]:
    """Facts by subject, attribute and scope, as of a valid day and a transaction time.

    `known_at=None` means "what the engine believes now" (live rows only). `scope` matches keys
    exactly (e.g. {"client": "Infra"}); facts without that key are general and also match when
    `scope` asks for {"client": None}.
    """
    q = (
        select(Fact, Entity.name, Source.short_label, Passage.locator)
        .join(Entity, Entity.id == Fact.subject_id)
        .outerjoin(Source, Source.id == Fact.source_id)
        .outerjoin(Passage, Passage.id == Fact.passage_id)
        .where(Fact.tenant_id == tenant(), *_time_filters(valid_on, known_at))
    )
    if subject_id is not None:
        q = q.where(Fact.subject_id == subject_id)
    if attribute is not None:
        attrs = [attribute] if isinstance(attribute, str) else attribute
        q = q.where(Fact.attribute.in_(attrs))
    if statuses:
        q = q.where(Fact.status.in_(statuses))
    if kinds:
        q = q.where(Fact.kind.in_(kinds))
    for k, v in (scope or {}).items():
        if v is None:
            q = q.where(or_(Fact.scope[k].astext.is_(None), Fact.scope[k].astext == "all"))
        else:
            q = q.where(Fact.scope[k].astext == str(v))
    q = q.order_by(Fact.authority_rank, Fact.valid_from.desc().nulls_last(), Fact.id)
    return [_row(f, n, lbl, loc) for f, n, lbl, loc in session.execute(q)]


def live_by_origin(session: Session, origin_keys: list[str]) -> dict[str, FactRow]:
    if not origin_keys:
        return {}
    q = select(Fact).where(
        Fact.tenant_id == tenant(), Fact.retracted_at.is_(None), Fact.origin_key.in_(origin_keys)
    )
    return {f.origin_key: _row(f) for f in session.scalars(q)}


def live_for_passages(session: Session, passage_ids: list[str]) -> list[FactRow]:
    q = select(Fact).where(
        Fact.tenant_id == tenant(), Fact.retracted_at.is_(None), Fact.passage_id.in_(passage_ids)
    )
    return [_row(f) for f in session.scalars(q)]


def related(session: Session, subject_id: str, attribute: str) -> list[FactRow]:
    """Live facts in one (subject, attribute) group: all a new fact is compared against."""
    return get_facts(session, subject_id=subject_id, attribute=attribute)


def groups_touched(session: Session, origin_keys: list[str]) -> set[tuple[str, str]]:
    q = select(Fact.subject_id, Fact.attribute).where(
        Fact.tenant_id == tenant(), Fact.origin_key.in_(origin_keys), Fact.retracted_at.is_(None)
    )
    return {(s, a) for s, a in session.execute(q)}


def count_live(session: Session, **where: Any) -> int:
    conds = [Fact.tenant_id == tenant(), Fact.retracted_at.is_(None)]
    conds += [getattr(Fact, k) == v for k, v in where.items()]
    return session.scalar(select(func.count()).select_from(Fact).where(and_(*conds))) or 0


def total_rows(session: Session) -> int:
    return (
        session.scalar(select(func.count()).select_from(Fact).where(Fact.tenant_id == tenant()))
        or 0
    )


def summary(session: Session) -> dict[str, Any]:
    live = [Fact.tenant_id == tenant(), Fact.retracted_at.is_(None)]
    by_status = dict(
        session.execute(select(Fact.status, func.count()).where(*live).group_by(Fact.status)).all()
    )
    by_attr = dict(
        session.execute(
            select(Fact.attribute, func.count()).where(*live).group_by(Fact.attribute)
        ).all()
    )
    return {"by_status": by_status, "by_attribute": by_attr, "rows_total": total_rows(session)}


def set_supersedes(session: Session, fact_id: int, loser_id: int) -> None:
    """Link a fact version written in this transaction to the version it supersedes."""
    session.execute(update(Fact).where(Fact.id == fact_id).values(supersedes_id=loser_id))


def live_with_attribute_prefix(session: Session, prefix: str) -> list[FactRow]:
    """Live facts whose attribute starts with `prefix` (e.g. "other:" proposals)."""
    q = (
        select(Fact, Entity.name)
        .join(Entity, Entity.id == Fact.subject_id)
        .where(
            Fact.tenant_id == tenant(),
            Fact.retracted_at.is_(None),
            Fact.attribute.startswith(prefix),
        )
        .order_by(Fact.attribute, Fact.id)
    )
    return [_row(f, n) for f, n in session.execute(q)]


def _joined():  # type: ignore[no-untyped-def]
    return (
        select(Fact, Entity.name, Source.short_label, Passage.locator)
        .join(Entity, Entity.id == Fact.subject_id)
        .outerjoin(Source, Source.id == Fact.source_id)
        .outerjoin(Passage, Passage.id == Fact.passage_id)
    )


def _narrow(q, statuses: list[str] | None, kinds: list[str] | None):  # type: ignore[no-untyped-def]
    if statuses:
        q = q.where(Fact.status.in_(statuses))
    if kinds:
        q = q.where(Fact.kind.in_(kinds))
    return q


def facts_touching(
    session: Session,
    entity_ids: list[str],
    valid_on: date | datetime | None = None,
    known_at: datetime | None = None,
    statuses: list[str] | None = None,
    kinds: list[str] | None = None,
    limit: int = 300,
) -> list[FactRow]:
    """Facts whose subject or object is one of `entity_ids` (one hop in the graph)."""
    if not entity_ids:
        return []
    q = _joined().where(
        Fact.tenant_id == tenant(),
        *_time_filters(valid_on, known_at),
        or_(Fact.subject_id.in_(entity_ids), Fact.object_id.in_(entity_ids)),
    )
    q = _narrow(q, statuses, kinds).order_by(Fact.authority_rank, Fact.id).limit(limit)
    return [_row(f, n, lbl, loc) for f, n, lbl, loc in session.execute(q)]


def nearest(
    session: Session,
    vec: list[float],
    k: int,
    valid_on: date | datetime | None = None,
    known_at: datetime | None = None,
    statuses: list[str] | None = None,
    kinds: list[str] | None = None,
) -> list[tuple[FactRow, float]]:
    """Facts nearest to `vec` by embedding (cosine similarity), filtered by time and status."""
    dist = Fact.embedding.cosine_distance(vec)
    q = (
        _joined()
        .add_columns(1 - dist)
        .where(
            Fact.tenant_id == tenant(),
            Fact.embedding.is_not(None),
            *_time_filters(valid_on, known_at),
        )
    )
    q = _narrow(q, statuses, kinds).order_by(dist).limit(k)
    return [(_row(f, n, lbl, loc), float(s)) for f, n, lbl, loc, s in session.execute(q)]


def nearest_current(
    session: Session, fact_ids: list[int], k: int = 3, min_sim: float = 0.8
) -> list[tuple[int, int, float]]:
    """(fact id, in-force rule id, similarity): for each of `fact_ids`, the `k` live rules (not
    practice) in force (current or corroborating) nearest by embedding, outside the fact's own
    group. A general fact (no client) is compared with every client's rules: an FAQ that says
    "10% on cement" for everyone contradicts a client memo for that client."""
    if not fact_ids:
        return []
    rows = session.execute(
        text(
            """
            SELECT f.id, c.id, c.sim FROM facts f
            CROSS JOIN LATERAL (
                SELECT g.id, 1 - (g.embedding <=> f.embedding) AS sim FROM facts g
                WHERE g.tenant_id = f.tenant_id AND g.retracted_at IS NULL
                  AND g.status IN ('current', 'corroborating') AND g.kind <> 'practice'
                  AND g.embedding IS NOT NULL AND g.id <> f.id
                  AND left(g.attribute, 6) <> 'other:'
                  AND (COALESCE(f.scope->>'client', 'all') = 'all'
                       OR COALESCE(g.scope->>'client', 'all')
                          = COALESCE(f.scope->>'client', 'all'))
                  AND NOT (g.attribute = f.attribute
                           AND COALESCE(g.scope->>'client', 'all')
                               = COALESCE(f.scope->>'client', 'all'))
                ORDER BY g.embedding <=> f.embedding
                LIMIT :k
            ) c
            WHERE f.id = ANY(:ids) AND f.tenant_id = :t AND f.embedding IS NOT NULL
              AND c.sim >= :min_sim
            """
        ),
        {"ids": list(fact_ids), "t": tenant(), "k": k, "min_sim": min_sim},
    )
    return [(a, b, float(s)) for a, b, s in rows]


def similarity(session: Session, fact_ids: list[int], vec: list[float]) -> dict[int, float]:
    """Cosine similarity of each fact's embedding to `vec` (facts without one are left out)."""
    if not fact_ids:
        return {}
    q = select(Fact.id, 1 - Fact.embedding.cosine_distance(vec)).where(
        Fact.tenant_id == tenant(), Fact.id.in_(fact_ids), Fact.embedding.is_not(None)
    )
    return {i: float(s) for i, s in session.execute(q)}


def by_ids(session: Session, fact_ids: list[int]) -> dict[int, FactRow]:
    if not fact_ids:
        return {}
    q = _joined().where(Fact.tenant_id == tenant(), Fact.id.in_(fact_ids))
    return {f.id: _row(f, n, lbl, loc) for f, n, lbl, loc in session.execute(q)}


def live_for_episode(
    session: Session, episode_id: str, statuses: list[str] | None = None
) -> list[FactRow]:
    q = select(Fact).where(
        Fact.tenant_id == tenant(), Fact.retracted_at.is_(None), Fact.episode_id == episode_id
    )
    if statuses:
        q = q.where(Fact.status.in_(statuses))
    return [_row(f) for f in session.scalars(q.order_by(Fact.id))]


def in_force_values(session: Session, limit_per_attribute: int = 3) -> dict[str, list[str]]:
    """Attribute -> value texts of its live rules in force now (current or provisional)."""
    q = (
        select(Fact.attribute, Fact.value)
        .where(
            Fact.tenant_id == tenant(),
            Fact.retracted_at.is_(None),
            Fact.status.in_(["current", "provisional"]),
            Fact.kind != "practice",
        )
        .order_by(Fact.attribute, Fact.authority_rank, Fact.id)
    )
    out: dict[str, list[str]] = {}
    for attr, value in session.execute(q):
        texts = out.setdefault(attr, [])
        t = str((value or {}).get("text") or "")
        if t and t not in texts and len(texts) < limit_per_attribute:
            texts.append(t)
    return out


def live_groups(session: Session) -> set[tuple[str, str]]:
    """Every (subject, attribute) group that has a live fact (for a full re-resolution)."""
    q = select(Fact.subject_id, Fact.attribute).where(
        Fact.tenant_id == tenant(), Fact.retracted_at.is_(None)
    )
    return {(sid, attr) for sid, attr in session.execute(q.distinct())}
