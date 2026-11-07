"""Episodes (raw input, never deleted), their sources and passages."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.store.base import stable_id, tenant, utcnow
from app.store.models import Episode, Passage, Source

# ---------------------------------------------------------------- episodes


def add_episode(
    session: Session,
    *,
    channel: str,
    content_hash: str,
    received_at: datetime,
    source_uri: str | None = None,
    blob_path: str | None = None,
    mime: str | None = None,
    sender: str | None = None,
    sender_role: str | None = None,
    effective_hint: date | None = None,
    scope_hint: str | None = None,
    meta: dict[str, Any] | None = None,
) -> tuple[str, bool]:
    """Insert an episode unless the same content exists. Returns (episode_id, created).

    A duplicate counts as a confirmation of the first episode.
    """
    t = tenant()
    existing = session.scalar(
        select(Episode.id).where(Episode.tenant_id == t, Episode.content_hash == content_hash)
    )
    if existing:
        session.execute(
            update(Episode)
            .where(Episode.id == existing)
            .values(confirmations=Episode.confirmations + 1)
        )
        return existing, False
    eid = stable_id(t, content_hash)
    session.add(
        Episode(
            id=eid,
            tenant_id=t,
            channel=channel,
            content_hash=content_hash,
            received_at=received_at,
            source_uri=source_uri,
            blob_path=blob_path,
            mime=mime,
            sender=sender,
            sender_role=sender_role,
            effective_hint=effective_hint,
            scope_hint=scope_hint,
            status="queued",
            meta=meta or {},
        )
    )
    session.flush()
    return eid, True


def get_episode(session: Session, episode_id: str) -> Episode | None:
    ep = session.get(Episode, episode_id)
    return ep if ep is not None and ep.tenant_id == tenant() else None


def set_status(session: Session, episode_id: str, status: str, **values: Any) -> None:
    session.execute(update(Episode).where(Episode.id == episode_id).values(status=status, **values))


def list_episodes(session: Session, limit: int = 200) -> list[Episode]:
    q = (
        select(Episode)
        .where(Episode.tenant_id == tenant())
        .order_by(Episode.received_at.desc(), Episode.created_at.desc())
        .limit(limit)
    )
    return list(session.scalars(q))


def episode_counts(session: Session) -> dict[str, int]:
    rows = session.execute(
        select(Episode.status, func.count())
        .where(Episode.tenant_id == tenant())
        .group_by(Episode.status)
    )
    return dict(rows.all())


# ---------------------------------------------------------------- sources


def upsert_source(session: Session, values: dict[str, Any]) -> str:
    values = {"tenant_id": tenant(), **values}
    stmt = pg_insert(Source).values(**values)
    cols = {k: stmt.excluded[k] for k in values if k not in ("id", "tenant_id", "confirmed_by")}
    session.execute(stmt.on_conflict_do_update(index_elements=["id"], set_=cols))
    return values["id"]


def update_source(session: Session, source_id: str, **values: Any) -> None:
    session.execute(update(Source).where(Source.id == source_id).values(**values))


def get_source(session: Session, source_id: str) -> Source | None:
    return session.get(Source, source_id)


def list_sources(session: Session, episode_id: str | None = None) -> list[Source]:
    q = select(Source).where(Source.tenant_id == tenant())
    if episode_id:
        q = q.where(Source.episode_id == episode_id)
    return list(session.scalars(q.order_by(Source.episode_id, Source.ordinal)))


# ---------------------------------------------------------------- passages


def upsert_passages(session: Session, rows: list[dict[str, Any]]) -> dict[str, int]:
    """Insert new passages, update changed ones, leave identical ones. Returns counts."""
    if not rows:
        return {"inserted": 0, "updated": 0, "unchanged": 0}
    t = tenant()
    ids = [r["id"] for r in rows]
    existing = dict(
        session.execute(select(Passage.id, Passage.content_hash).where(Passage.id.in_(ids))).all()
    )
    counts = {"inserted": 0, "updated": 0, "unchanged": 0}
    new = [r for r in rows if r["id"] not in existing]
    # Parents first so parent_id foreign keys resolve.
    for wave in (
        [r for r in new if r.get("parent_id") is None],
        [r for r in new if r.get("parent_id") is not None],
    ):
        for i in range(0, len(wave), 1000):
            session.execute(pg_insert(Passage), [{"tenant_id": t, **r} for r in wave[i : i + 1000]])
    counts["inserted"] = len(new)
    for r in rows:
        old = existing.get(r["id"])
        if old is None:
            continue
        if old != r["content_hash"]:
            session.execute(
                update(Passage).where(Passage.id == r["id"]).values(retired_at=None, **r)
            )
            counts["updated"] += 1
        else:
            counts["unchanged"] += 1
    session.flush()
    return counts


def update_passage(session: Session, passage_id: str, **values: Any) -> None:
    session.execute(update(Passage).where(Passage.id == passage_id).values(**values))


def retire_passages(session: Session, passage_ids: list[str]) -> None:
    if passage_ids:
        session.execute(
            update(Passage).where(Passage.id.in_(passage_ids)).values(retired_at=utcnow())
        )


def passages_for_source(session: Session, source_id: str, live: bool = True) -> list[Passage]:
    q = select(Passage).where(Passage.source_id == source_id)
    if live:
        q = q.where(Passage.retired_at.is_(None))
    return list(session.scalars(q.order_by(Passage.ordinal)))


def passages_for_episode(session: Session, episode_id: str) -> list[Passage]:
    q = (
        select(Passage)
        .where(Passage.episode_id == episode_id, Passage.retired_at.is_(None))
        .order_by(Passage.source_id, Passage.ordinal)
    )
    return list(session.scalars(q))


def get_passage(session: Session, passage_id: str) -> Passage | None:
    return session.get(Passage, passage_id)


def all_passages(session: Session) -> list[Passage]:
    q = (
        select(Passage)
        .where(Passage.tenant_id == tenant(), Passage.retired_at.is_(None))
        .order_by(Passage.episode_id, Passage.source_id, Passage.ordinal)
    )
    return list(session.scalars(q))


def set_passage_embeddings(session: Session, vectors: dict[str, list[float]]) -> None:
    for pid, vec in vectors.items():
        session.execute(update(Passage).where(Passage.id == pid).values(embedding=vec))


def delete_tenant_content(session: Session) -> None:  # tests and fresh-tenant runs only
    from app.store.models import (
        Change,
        Conflict,
        Entity,
        EntityAlias,
        Fact,
        Job,
        KbVersion,
        PluginBinding,
        ReviewItem,
        Schema,
    )

    t = tenant()
    for model in (
        Change,
        Conflict,
        ReviewItem,
        Fact,
        PluginBinding,
        EntityAlias,
        Job,
        KbVersion,
        Schema,
    ):
        session.execute(delete(model).where(model.tenant_id == t))
    session.execute(update(Entity).where(Entity.tenant_id == t).values(merged_into=None))
    session.execute(delete(Entity).where(Entity.tenant_id == t))
    session.execute(update(Passage).where(Passage.tenant_id == t).values(parent_id=None))
    session.execute(delete(Passage).where(Passage.tenant_id == t))
    session.execute(update(Source).where(Source.tenant_id == t).values(supersedes_source_id=None))
    session.execute(delete(Source).where(Source.tenant_id == t))
    session.execute(delete(Episode).where(Episode.tenant_id == t))


def sources_by_ids(session: Session, ids: list[str]) -> dict[str, Source]:
    if not ids:
        return {}
    return {s.id: s for s in session.scalars(select(Source).where(Source.id.in_(ids)))}


def passages_by_ids(session: Session, ids: list[str]) -> dict[str, Passage]:
    if not ids:
        return {}
    return {p.id: p for p in session.scalars(select(Passage).where(Passage.id.in_(ids)))}


def extractable_passages(session: Session, episode_id: str | None = None) -> list[Passage]:
    """Live leaf passages that carry statements (records and parents are not sent to the LLM)."""
    q = select(Passage).where(
        Passage.tenant_id == tenant(),
        Passage.retired_at.is_(None),
        Passage.segment_kind.not_in(["record", "table"]),
        Passage.meta["leaf"].astext == "true",
    )
    if episode_id:
        q = q.where(Passage.episode_id == episode_id)
    return list(session.scalars(q.order_by(Passage.episode_id, Passage.source_id, Passage.ordinal)))


def parsed_episode_ids(session: Session) -> list[str]:
    q = select(Episode.id).where(
        Episode.tenant_id == tenant(), Episode.status.in_(["parsed", "extracted", "published"])
    )
    return list(session.scalars(q.order_by(Episode.received_at, Episode.id)))
