"""Bitemporal fact rows. All fact reads and writes go through here.

Valid time: [valid_from, valid_to). Transaction time: [recorded_at, retracted_at).
A row is never changed after insert except for closing `retracted_at`. A change of belief about a
fact (status, validity) retracts the live row and inserts a new version with the same origin_key.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import date, datetime
from typing import Any

from sqlalchemy import and_, func, or_, select, update
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
