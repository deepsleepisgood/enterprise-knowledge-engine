"""Schemas, kb versions and changes, conflicts, review items and plug-in bindings."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.store.base import tenant, utcnow
from app.store.models import (
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
    return c.id


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
