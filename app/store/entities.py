"""Entities and their aliases."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.store.base import has_extension, norm_name, stable_id, tenant
from app.store.models import Entity, EntityAlias


@dataclass
class EntityRow:
    id: str
    type: str
    name: str
    aliases: list[str]
    score: float = 0.0


def _resolve_merged(session: Session, entity_id: str) -> str:
    seen = set()
    while entity_id not in seen:
        seen.add(entity_id)
        nxt = session.scalar(select(Entity.merged_into).where(Entity.id == entity_id))
        if not nxt:
            return entity_id
        entity_id = nxt
    return entity_id


def by_alias(session: Session, alias: str, type_: str | None = None) -> str | None:
    q = (
        select(EntityAlias.entity_id)
        .join(Entity, Entity.id == EntityAlias.entity_id)
        .where(EntityAlias.tenant_id == tenant(), EntityAlias.alias_norm == norm_name(alias))
    )
    if type_:
        q = q.where(Entity.type == type_)
    eid = session.scalar(q.limit(1))
    return _resolve_merged(session, eid) if eid else None


def create(
    session: Session,
    type_: str,
    name: str,
    embedding: list[float] | None = None,
    summary: str | None = None,
    attrs: dict[str, Any] | None = None,
    episode_id: str | None = None,
) -> str:
    t = tenant()
    eid = stable_id(t, type_, norm_name(name))
    session.execute(
        pg_insert(Entity)
        .values(
            id=eid,
            tenant_id=t,
            type=type_,
            name=name,
            embedding=embedding,
            summary=summary,
            attrs=attrs or {},
        )
        .on_conflict_do_nothing(index_elements=["id"])
    )
    add_alias(session, eid, name, episode_id)
    return eid


def pin(session: Session, type_: str, name: str, episode_id: str | None = None) -> str:
    """The entity named exactly `name` (created if needed). The name stops being an alias of
    any other entity of the type, so an earlier wrong merge (a subsidiary filed under its
    parent group) is undone for future lookups."""
    eid = create(session, type_, name, episode_id=episode_id)
    others = select(Entity.id).where(
        Entity.tenant_id == tenant(), Entity.type == type_, Entity.id != eid
    )
    session.execute(
        delete(EntityAlias).where(
            EntityAlias.tenant_id == tenant(),
            EntityAlias.alias_norm == norm_name(name),
            EntityAlias.entity_id.in_(others),
        )
    )
    return eid


def add_alias(session: Session, entity_id: str, alias: str, episode_id: str | None = None) -> None:
    session.execute(
        pg_insert(EntityAlias)
        .values(
            tenant_id=tenant(),
            entity_id=entity_id,
            alias=alias,
            alias_norm=norm_name(alias),
            episode_id=episode_id,
        )
        .on_conflict_do_nothing(constraint="uq_alias")
    )


def get(session: Session, entity_id: str) -> EntityRow | None:
    e = session.get(Entity, entity_id)
    if e is None or e.tenant_id != tenant():
        return None
    aliases = list(
        session.scalars(select(EntityAlias.alias).where(EntityAlias.entity_id == entity_id))
    )
    return EntityRow(e.id, e.type, e.name, aliases)


def list_entities(session: Session, type_: str | None = None) -> list[EntityRow]:
    q = select(Entity).where(Entity.tenant_id == tenant(), Entity.merged_into.is_(None))
    if type_:
        q = q.where(Entity.type == type_)
    ents = list(session.scalars(q.order_by(Entity.type, Entity.name)))
    alias_rows = session.execute(
        select(EntityAlias.entity_id, EntityAlias.alias).where(EntityAlias.tenant_id == tenant())
    ).all()
    by: dict[str, list[str]] = {}
    for eid, a in alias_rows:
        by.setdefault(eid, []).append(a)
    return [EntityRow(e.id, e.type, e.name, by.get(e.id, [])) for e in ents]


def candidates(
    session: Session,
    name: str,
    type_: str | None,
    embedding: list[float] | None = None,
    limit: int = 5,
) -> list[EntityRow]:
    """Similar entities by name (trigram, or Python similarity without pg_trgm) and embedding."""
    t = tenant()
    found: dict[str, float] = {}
    key = norm_name(name)
    if has_extension(session, "pg_trgm"):
        rows = session.execute(
            text(
                "SELECT a.entity_id, max(similarity(a.alias_norm, :n)) AS s "
                "FROM entity_aliases a JOIN entities e ON e.id = a.entity_id "
                "WHERE a.tenant_id = :t AND (:ty IS NULL OR e.type = :ty) "
                "AND a.alias_norm % :n GROUP BY a.entity_id ORDER BY s DESC LIMIT :k"
            ),
            {"n": key, "t": t, "ty": type_, "k": limit},
        ).all()
        found.update({eid: float(s) for eid, s in rows})
    else:
        q = (
            select(EntityAlias.entity_id, EntityAlias.alias_norm)
            .join(Entity, Entity.id == EntityAlias.entity_id)
            .where(EntityAlias.tenant_id == t)
        )
        if type_:
            q = q.where(Entity.type == type_)
        for eid, a in session.execute(q):
            s = SequenceMatcher(None, key, a).ratio()
            if s >= 0.5 and s > found.get(eid, 0):
                found[eid] = s
    if embedding is not None:
        q = (
            select(Entity.id, 1 - Entity.embedding.cosine_distance(embedding))
            .where(Entity.tenant_id == t, Entity.embedding.is_not(None))
            .order_by(Entity.embedding.cosine_distance(embedding))
            .limit(limit)
        )
        if type_:
            q = q.where(Entity.type == type_)
        for eid, sim in session.execute(q):
            found[eid] = max(found.get(eid, 0.0), float(sim))
    out = []
    for eid, score in sorted(found.items(), key=lambda kv: -kv[1])[:limit]:
        eid = _resolve_merged(session, eid)
        row = get(session, eid)
        if row:
            row.score = score
            out.append(row)
    return out


def merge(session: Session, keep_id: str, drop_id: str) -> None:
    """Owner correction: `drop_id` becomes an alias of `keep_id`. Facts keep their subject id and
    are read through `merged_into`."""
    session.execute(update(Entity).where(Entity.id == drop_id).values(merged_into=keep_id))
    for alias in session.scalars(select(EntityAlias.alias).where(EntityAlias.entity_id == drop_id)):
        add_alias(session, keep_id, alias)


def count(session: Session) -> dict[str, int]:
    rows = session.execute(
        select(Entity.type, func.count())
        .where(Entity.tenant_id == tenant(), Entity.merged_into.is_(None))
        .group_by(Entity.type)
    )
    return dict(rows.all())
