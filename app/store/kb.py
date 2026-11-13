"""Schemas, kb versions and changes, conflicts, review items and plug-in bindings."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.store.base import tenant, utcnow
from app.store.models import (
    Ack,
    Change,
    Conflict,
    KbVersion,
    PluginBinding,
    ReviewItem,
    Schema,
)

# ---------------------------------------------------------------- schemas


def save_schema(
    session: Session,
    ontology: dict[str, Any],
    mode: str,
    sample: list[str] | None = None,
    frozen_by: str | None = None,
) -> int:
    t = tenant()
    version = (
        session.scalar(select(func.max(Schema.version)).where(Schema.tenant_id == t)) or 0
    ) + 1
    s = Schema(
        tenant_id=t,
        version=version,
        mode=mode,
        ontology=ontology,
        sample=sample or [],
        status="frozen" if frozen_by else "draft",
        frozen_at=utcnow() if frozen_by else None,
        frozen_by=frozen_by,
    )
    session.add(s)
    session.flush()
    return s.version


def freeze_schema(session: Session, version: int, by: str) -> None:
    session.execute(
        update(Schema)
        .where(Schema.tenant_id == tenant(), Schema.version == version)
        .values(status="frozen", frozen_at=utcnow(), frozen_by=by)
    )


def update_schema(session: Session, version: int, ontology: dict[str, Any]) -> None:
    session.execute(
        update(Schema)
        .where(Schema.tenant_id == tenant(), Schema.version == version, Schema.status == "draft")
        .values(ontology=ontology)
    )


def active_schema(session: Session, mode: str | None = None) -> Schema | None:
    """Latest frozen schema (of `mode` if given), else the latest draft."""
    q = select(Schema).where(Schema.tenant_id == tenant())
    if mode:
        q = q.where(Schema.mode == mode)
    frozen = session.scalar(
        q.where(Schema.status == "frozen").order_by(Schema.version.desc()).limit(1)
    )
    return frozen or session.scalar(q.order_by(Schema.version.desc()).limit(1))


def latest_schema(session: Session, mode: str | None = None) -> Schema | None:
    """Highest schema version (of `mode` if given), frozen or draft."""
    q = select(Schema).where(Schema.tenant_id == tenant())
    if mode:
        q = q.where(Schema.mode == mode)
    return session.scalar(q.order_by(Schema.version.desc()).limit(1))


# ---------------------------------------------------------------- versions and changes


def current_kb_version(session: Session) -> int:
    return (
        session.scalar(select(func.max(KbVersion.id)).where(KbVersion.tenant_id == tenant())) or 0
    )


def bump_kb_version(session: Session, summary: str) -> int:
    v = KbVersion(tenant_id=tenant(), summary=summary)
    session.add(v)
    session.flush()
    return v.id


def record_change(
    session: Session,
    kb_version: int,
    summary: str,
    new_fact: int | None = None,
    old_fact: int | None = None,
    effective_at: datetime | None = None,
    source_episode: str | None = None,
) -> int:
    c = Change(
        tenant_id=tenant(),
        kb_version=kb_version,
        summary=summary,
        new_fact=new_fact,
        old_fact=old_fact,
        effective_at=effective_at,
        source_episode=source_episode,
    )
    session.add(c)
    session.flush()
    if old_fact is not None:  # a fact someone may have relied on closed: recall their answers
        from app.store import jobs

        jobs.enqueue_once(session, "answer_recall", {})
    return c.id


def changes_retiring(session: Session, since: datetime) -> list[Change]:
    """Changes since `since` that retired or replaced a fact (they name `old_fact`)."""
    q = select(Change).where(
        Change.tenant_id == tenant(), Change.old_fact.is_not(None), Change.created_at >= since
    )
    return list(session.scalars(q.order_by(Change.id)))


def changes_between(session: Session, start: datetime, end: datetime) -> list[Change]:
    """Changes recorded in [start, end), oldest first."""
    q = select(Change).where(
        Change.tenant_id == tenant(), Change.created_at >= start, Change.created_at < end
    )
    return list(session.scalars(q.order_by(Change.id)))


def acked_by(session: Session, user_id: str, change_ids: list[int]) -> set[int]:
    if not change_ids:
        return set()
    q = select(Ack.change_id).where(
        Ack.tenant_id == tenant(), Ack.user_id == user_id, Ack.change_id.in_(change_ids)
    )
    return set(session.scalars(q))


def last_change_id(session: Session) -> int:
    return session.scalar(select(func.max(Change.id)).where(Change.tenant_id == tenant())) or 0


def changes_since(session: Session, kb_version: int = 0, limit: int = 100) -> list[Change]:
    q = (
        select(Change)
        .where(Change.tenant_id == tenant(), Change.kb_version > kb_version)
        .order_by(Change.id.desc())
        .limit(limit)
    )
    return list(session.scalars(q))


# ---------------------------------------------------------------- conflicts


def add_conflict(session: Session, **values: Any) -> int | None:
    a, b = sorted((values.pop("fact_a"), values.pop("fact_b")))
    stmt = (
        pg_insert(Conflict)
        .values(tenant_id=tenant(), fact_a=a, fact_b=b, **values)
        .on_conflict_do_nothing(constraint="uq_conflicts_pair")
        .returning(Conflict.id)
    )
    return session.scalar(stmt)


def upsert_conflict(session: Session, **values: Any) -> int:
    """Record a conflict found by a scan; a pair seen before keeps its id and owner status
    (a dismissed conflict stays dismissed) but takes the new reason."""
    a, b = sorted((values.pop("fact_a"), values.pop("fact_b")))
    stmt = pg_insert(Conflict).values(tenant_id=tenant(), fact_a=a, fact_b=b, **values)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_conflicts_pair",
        set_={
            "reason": stmt.excluded.reason,
            "authoritative_fact": stmt.excluded.authoritative_fact,
        },
    ).returning(Conflict.id)
    return int(session.scalar(stmt))


def clear_conflicts_except(session: Session, keep: set[int]) -> int:
    """After a full scan: open conflicts it no longer finds are marked `cleared` (kept, never
    deleted, so the history of what was flagged survives)."""
    q = update(Conflict).where(Conflict.tenant_id == tenant(), Conflict.status == "open")
    if keep:
        q = q.where(Conflict.id.not_in(keep))
    return session.execute(q.values(status="cleared")).rowcount or 0


def list_conflicts(session: Session, status: str | None = None) -> list[Conflict]:
    q = select(Conflict).where(Conflict.tenant_id == tenant())
    if status:
        q = q.where(Conflict.status == status)
    return list(session.scalars(q.order_by(Conflict.id)))


# ---------------------------------------------------------------- review queue


def add_review_item(
    session: Session, kind: str, payload: dict[str, Any], risk_tier: str = "normal"
) -> int:
    r = ReviewItem(tenant_id=tenant(), kind=kind, payload=payload, risk_tier=risk_tier)
    session.add(r)
    session.flush()
    return r.id


def list_review_items(session: Session, status: str = "open") -> list[ReviewItem]:
    q = select(ReviewItem).where(ReviewItem.tenant_id == tenant(), ReviewItem.status == status)
    return list(session.scalars(q.order_by(ReviewItem.id)))


# ---------------------------------------------------------------- plug-in bindings


def put_binding(session: Session, plugin: str, param: str, **values: Any) -> None:
    stmt = pg_insert(PluginBinding).values(tenant_id=tenant(), plugin=plugin, param=param, **values)
    session.execute(
        stmt.on_conflict_do_update(
            constraint="uq_binding", set_={**values, "updated_at": func.now()}
        )
    )


def get_bindings(session: Session, plugin: str | None = None) -> list[PluginBinding]:
    q = select(PluginBinding).where(PluginBinding.tenant_id == tenant())
    if plugin:
        q = q.where(PluginBinding.plugin == plugin)
    return list(session.scalars(q.order_by(PluginBinding.plugin, PluginBinding.param)))


def get_schema(session: Session, version: int) -> Schema | None:
    return session.scalar(
        select(Schema).where(Schema.tenant_id == tenant(), Schema.version == version)
    )


def decide_review_item(
    session: Session,
    item_id: int,
    status: str,
    by: str,
    row_version: int | None = None,
    payload: dict[str, Any] | None = None,
) -> bool:
    """Record a decision. With `row_version`, only if nobody decided or edited the item since
    (optimistic lock): returns False when the version no longer matches."""
    where = [ReviewItem.tenant_id == tenant(), ReviewItem.id == item_id]
    if row_version is not None:
        where.append(ReviewItem.row_version == row_version)
    values: dict[str, Any] = {
        "status": status,
        "decided_by": by,
        "decided_at": utcnow(),
        "row_version": ReviewItem.row_version + 1,
    }
    if payload is not None:
        values["payload"] = payload
    res = session.execute(update(ReviewItem).where(*where).values(**values))
    return bool(res.rowcount)


def get_review_item(session: Session, item_id: int) -> ReviewItem | None:
    return session.scalar(
        select(ReviewItem).where(ReviewItem.tenant_id == tenant(), ReviewItem.id == item_id)
    )


# ---------------------------------------------------------------- acknowledgements


def ack_change(session: Session, change_id: int, user_id: str) -> None:
    session.execute(
        pg_insert(Ack)
        .values(tenant_id=tenant(), change_id=change_id, user_id=user_id)
        .on_conflict_do_nothing(constraint="uq_ack")
    )


def ack_counts(session: Session, change_ids: list[int]) -> dict[int, int]:
    if not change_ids:
        return {}
    rows = session.execute(
        select(Ack.change_id, func.count())
        .where(Ack.tenant_id == tenant(), Ack.change_id.in_(change_ids))
        .group_by(Ack.change_id)
    )
    return dict(rows.all())


def get_change(session: Session, change_id: int) -> Change | None:
    return session.scalar(
        select(Change).where(Change.tenant_id == tenant(), Change.id == change_id)
    )


def get_conflict(session: Session, conflict_id: int) -> Conflict | None:
    return session.scalar(
        select(Conflict).where(Conflict.tenant_id == tenant(), Conflict.id == conflict_id)
    )


def set_conflict_status(session: Session, conflict_id: int, status: str) -> bool:
    res = session.execute(
        update(Conflict)
        .where(Conflict.tenant_id == tenant(), Conflict.id == conflict_id)
        .values(status=status)
    )
    return bool(res.rowcount)


def ping(session: Session) -> bool:
    return session.execute(select(1)).scalar() == 1


def discard_schema_draft(session: Session, version: int) -> bool:
    """Drop an unfrozen schema draft and its review item (a frozen schema is never removed)."""
    from sqlalchemy import delete

    t = tenant()
    res = session.execute(
        delete(Schema).where(
            Schema.tenant_id == t, Schema.version == version, Schema.status == "draft"
        )
    )
    if res.rowcount:
        session.execute(
            delete(ReviewItem).where(
                ReviewItem.tenant_id == t,
                ReviewItem.kind == "schema",
                ReviewItem.payload["version"].as_string() == str(version),
            )
        )
    return bool(res.rowcount)
