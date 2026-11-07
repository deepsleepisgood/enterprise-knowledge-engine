"""Shared helpers for the repository layer: tenant context, time conversion, capabilities."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, date, datetime, time, timedelta
from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.orm import Session

_tenant: ContextVar[str | None] = ContextVar("tenant", default=None)


def tenant() -> str:
    """The tenant for this call: set by `use_tenant`, else TENANT_ID from settings."""
    t = _tenant.get()
    if t:
        return t
    from app.core.config import get_settings

    return get_settings().tenant_id


@contextmanager
def use_tenant(tenant_id: str) -> Iterator[None]:
    token = _tenant.set(tenant_id)
    try:
        yield
    finally:
        _tenant.reset(token)


def utcnow() -> datetime:
    return datetime.now(UTC)


def day_start(d: date | datetime | None) -> datetime | None:
    """A calendar day as the instant it begins (UTC). Datetimes pass through."""
    if d is None:
        return None
    if isinstance(d, datetime):
        return d if d.tzinfo else d.replace(tzinfo=UTC)
    return datetime.combine(d, time.min, tzinfo=UTC)


def day_after(d: date | None) -> datetime | None:
    """Exclusive end of a validity interval whose last day in force is `d`."""
    return None if d is None else day_start(d + timedelta(days=1))


def last_day(valid_to: datetime | None) -> date | None:
    """The last day in force for an exclusive `valid_to` bound."""
    return None if valid_to is None else (valid_to - timedelta(days=1)).date()


def norm_name(s: str) -> str:
    """Normalised alias key: lower case, punctuation folded to spaces."""
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def stable_id(*parts: object, n: int = 20) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:n]


@lru_cache(maxsize=8)
def _extensions(url: str) -> frozenset[str]:  # cached per database
    from app.core.db import get_engine

    with get_engine().connect() as conn:
        rows = conn.execute(text("SELECT extname FROM pg_extension")).scalars()
        return frozenset(rows)


def has_extension(session: Session, name: str) -> bool:
    return name in _extensions(str(session.get_bind().url))
