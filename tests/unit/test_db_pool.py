"""The connection pool and answer concurrency come from settings, not library defaults."""

from __future__ import annotations

from app.core import db
from app.core.config import Settings, get_settings


def test_pool_defaults_cover_concurrent_answers() -> None:
    s = Settings(_env_file=None)
    # Two connections per answer being worked on (snapshot + parallel search), plus headroom.
    assert s.db_pool_size + s.db_max_overflow >= 2 * s.ask_concurrency
    assert s.db_pool_size + s.db_max_overflow > 15  # SQLAlchemy's default queued the 16th


def test_engine_uses_pool_settings(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/x")  # never connected
    monkeypatch.setenv("DB_POOL_SIZE", "7")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "9")
    monkeypatch.setenv("DB_POOL_TIMEOUT_S", "12")
    get_settings.cache_clear()
    db.get_engine.cache_clear()
    try:
        pool = db.get_engine().pool
        assert pool.size() == 7
        assert pool._max_overflow == 9
        assert pool._timeout == 12
        assert db.pool_status() == {"in_use": 0, "idle": 0, "max": 16}
    finally:
        get_settings.cache_clear()
        db.get_engine.cache_clear()
