"""Engine and session factory."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from typing import Any

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


def normalise_url(url: str) -> str:
    """Use the psycopg 3 driver whatever form the URL was given in."""
    for prefix in ("postgresql+psycopg://", "postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


@lru_cache
def get_engine() -> Engine:
    s = get_settings()
    url = normalise_url(s.resolved_database_url())
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=s.db_pool_size,
        max_overflow=s.db_max_overflow,
        pool_timeout=s.db_pool_timeout_s,
        future=True,
    )


def pool_status() -> dict[str, int]:
    """Connections this process holds: in use, idle, and the most it may open."""
    pool: Any = get_engine().pool
    s = get_settings()
    return {
        "in_use": int(pool.checkedout()),
        "idle": int(pool.checkedin()),
        "max": s.db_pool_size + s.db_max_overflow,
    }


@contextmanager
def session_scope() -> Iterator[Session]:
    """One transaction: commit on success, roll back on error."""
    factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


_SNAPSHOT_ID = re.compile(r"[0-9A-Fa-f-]{1,64}")


@contextmanager
def snapshot_scope(writable: bool = False, snapshot: str | None = None) -> Iterator[Session]:
    """A transaction on one snapshot: every read in it sees the same kb_version, whatever is
    published meanwhile (REPEATABLE READ in Postgres is snapshot isolation). Read-only unless
    `writable` (the answer path inserts its log row). `snapshot` joins a snapshot another open
    transaction exported with `export_snapshot`, so work split across connections (a search run
    in parallel) reads exactly the same data; it fails once that transaction has ended."""
    with session_scope() as session:
        mode = "" if writable else " READ ONLY"
        session.execute(text(f"SET TRANSACTION ISOLATION LEVEL REPEATABLE READ{mode}"))
        if snapshot is not None:
            if not _SNAPSHOT_ID.fullmatch(snapshot):
                raise ValueError(f"not a snapshot id: {snapshot!r}")
            session.execute(text(f"SET TRANSACTION SNAPSHOT '{snapshot}'"))
        yield session


def export_snapshot(session: Session) -> str:
    """The id other transactions pass to `snapshot_scope(snapshot=...)` to read the same data
    as `session` (valid while its transaction is open)."""
    return str(session.scalar(text("SELECT pg_export_snapshot()")))
