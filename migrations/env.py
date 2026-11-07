"""Alembic environment: the URL comes from app settings, never from alembic.ini."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context

from app.core.db import get_engine
from app.core.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_online() -> None:
    with get_engine().connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
