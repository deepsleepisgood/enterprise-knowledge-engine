"""Alembic environment: the URL comes from app settings, never from alembic.ini."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context

from app.core.db import get_engine
from app.store.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Indexes created by hand in migrations (expression, HNSW and trigram indexes).
MANUAL_INDEXES = {
    "ix_facts_valid",
    "ix_facts_known",
    "ix_passages_embedding",
    "ix_entities_embedding",
    "ix_facts_embedding",
    "ix_entities_name_trgm",
    "ix_alias_trgm",
}


def include_object(obj, name, type_, reflected, compare_to) -> bool:
    return not (type_ == "index" and name in MANUAL_INDEXES)


def run_migrations_online() -> None:
    with get_engine().connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
