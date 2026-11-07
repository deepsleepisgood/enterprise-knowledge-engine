"""Engine and session factory."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
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
    url = normalise_url(get_settings().resolved_database_url())
    return create_engine(url, pool_pre_ping=True, future=True)


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
