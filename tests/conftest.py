from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

# Inputs in tests are the owner's own seeding unless a test turns governance on itself.
os.environ.setdefault("GOVERNANCE", "false")
# No real vision model from a test run, whatever .env says (a test that wants one sets it).
os.environ["MODEL_VISION"] = ""

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TEST_DB = "ps07_test"

# Suites waiting for their v2 phase (see PROGRESS.md "v2 migration plan").
collect_ignore = []


def _server_url() -> str | None:
    """The server tests create their scratch database on: TEST_DATABASE_URL if set, else the
    embedded dev server. Never DATABASE_URL: that may be a deployed database."""
    if os.environ.get("TEST_DATABASE_URL"):
        return os.environ["TEST_DATABASE_URL"]
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        import dev_db  # type: ignore[import-not-found]

        return dev_db.start()
    except Exception as exc:  # pgserver missing or failed to start
        print(f"[conftest] no database available: {exc}")
        return None


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    import psycopg
    from sqlalchemy.engine import make_url

    base = _server_url()
    if base is None:
        pytest.skip("no Postgres available (set DATABASE_URL or install pgserver)")
    url = make_url(base.replace("postgresql://", "postgresql+psycopg://", 1))
    admin = url.set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
        conn.execute(f"CREATE DATABASE {TEST_DB}")
    test_url = url.set(database=TEST_DB).render_as_string(hide_password=False)

    from app.core import config, db

    old = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = test_url
    config.get_settings.cache_clear()
    db.get_engine.cache_clear()

    from alembic import command
    from alembic.config import Config

    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
    yield test_url

    db.get_engine().dispose()
    if old is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = old
    config.get_settings.cache_clear()
    db.get_engine.cache_clear()


@pytest.fixture
def db(database_url):
    """A clean default tenant in the test database (all content tables emptied)."""
    from app.core.db import session_scope
    from app.store.episodes import delete_tenant_content

    with session_scope() as s:
        delete_tenant_content(s)
    yield database_url
