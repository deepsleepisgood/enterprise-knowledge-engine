"""Generic bitemporal schema (BUILD_PLAN v2, Phase 0). Replaces the v1 claims schema.

pg_trgm and btree_gist are created only when the server offers them (the embedded dev
server does not; Neon does). Indexes that need them are skipped otherwise.

Revision ID: 0001
Revises: 
Create Date: 2026-11-07 17:33:42.954275
"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _available(name: str) -> bool:
    row = op.get_bind().execute(
        sa.text("SELECT 1 FROM pg_available_extensions WHERE name = :n"), {"n": name}
    )
    return row.first() is not None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    for ext in ("pg_trgm", "btree_gist"):
        if _available(ext):
            op.execute(f"CREATE EXTENSION IF NOT EXISTS {ext}")
    _tables()
    _extra_indexes()


def _extra_indexes() -> None:
    # Bitemporal range indexes (GiST on ranges works without btree_gist).
    op.execute(
        "CREATE INDEX ix_facts_valid ON facts USING gist (tstzrange(valid_from, valid_to))"
    )
    op.execute(
        "CREATE INDEX ix_facts_known ON facts USING gist (tstzrange(recorded_at, retracted_at))"
    )
    for table in ("passages", "entities", "facts"):
        op.execute(
            f"CREATE INDEX ix_{table}_embedding ON {table} "
            "USING hnsw (embedding vector_cosine_ops)"
        )
    if _available("pg_trgm"):
        op.execute("CREATE INDEX ix_entities_name_trgm ON entities USING gin (name gin_trgm_ops)")
        op.execute(
            "CREATE INDEX ix_alias_trgm ON entity_aliases USING gin (alias_norm gin_trgm_ops)"
        )


def _tables() -> None:
    op.create_table('answers_log',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('tenant_id', sa.String(length=64), server_default='default', nullable=False),
    sa.Column('user_id', sa.Text(), nullable=False),
    sa.Column('question', sa.Text(), nullable=False),
    sa.Column('client', sa.Text(), nullable=True),
    sa.Column('as_of', sa.Date(), nullable=True),
    sa.Column('kb_version', sa.Integer(), nullable=False),
    sa.Column('route', sa.String(length=64), nullable=False),
    sa.Column('card', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('cited_fact_ids', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('cited_passage_ids', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('latency_ms', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('entities',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('tenant_id', sa.String(length=64), server_default='default', nullable=False),
    sa.Column('type', sa.String(length=64), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('summary', sa.Text(), nullable=True),
    sa.Column('attrs', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('embedding', pgvector.sqlalchemy.vector.VECTOR(dim=384), nullable=True),
    sa.Column('merged_into', sa.String(length=40), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['merged_into'], ['entities.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_entities_tenant_type', 'entities', ['tenant_id', 'type'], unique=False)
    op.create_table('episodes',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('tenant_id', sa.String(length=64), server_default='default', nullable=False),
    sa.Column('channel', sa.String(length=32), nullable=False),
    sa.Column('source_uri', sa.Text(), nullable=True),
    sa.Column('blob_path', sa.Text(), nullable=True),
    sa.Column('mime', sa.String(length=128), nullable=True),
    sa.Column('sender', sa.Text(), nullable=True),
    sa.Column('sender_role', sa.Text(), nullable=True),
    sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('effective_hint', sa.Date(), nullable=True),
    sa.Column('scope_hint', sa.Text(), nullable=True),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('parse_tier', sa.Integer(), nullable=True),
    sa.Column('parse_quality', sa.Float(), nullable=True),
    sa.Column('triage_label', sa.String(length=32), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('confirmations', sa.Integer(), server_default='0', nullable=False),
    sa.Column('meta', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'content_hash', name='uq_episodes_hash')
    )
    op.create_table('jobs',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('tenant_id', sa.String(length=64), server_default='default', nullable=False),
    sa.Column('kind', sa.String(length=64), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('max_attempts', sa.Integer(), nullable=False),
    sa.Column('run_after', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('locked_by', sa.Text(), nullable=True),
    sa.Column('locked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_jobs_claim', 'jobs', ['status', 'run_after'], unique=False)
    op.create_table('kb_versions',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('tenant_id', sa.String(length=64), server_default='default', nullable=False),
    sa.Column('published_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('review_items',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('tenant_id', sa.String(length=64), server_default='default', nullable=False),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('risk_tier', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('row_version', sa.Integer(), nullable=False),
    sa.Column('decided_by', sa.Text(), nullable=True),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('schemas',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('tenant_id', sa.String(length=64), server_default='default', nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('mode', sa.String(length=16), nullable=False),
    sa.Column('ontology', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('sample', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('frozen_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('frozen_by', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'version', name='uq_schemas_version')
    )
    op.create_table('entity_aliases',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('tenant_id', sa.String(length=64), server_default='default', nullable=False),
    sa.Column('entity_id', sa.String(length=40), nullable=False),
    sa.Column('alias', sa.Text(), nullable=False),
    sa.Column('alias_norm', sa.Text(), nullable=False),
    sa.Column('episode_id', sa.String(length=40), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['entity_id'], ['entities.id'], ),
    sa.ForeignKeyConstraint(['episode_id'], ['episodes.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'entity_id', 'alias_norm', name='uq_alias')
    )
    op.create_index('ix_alias_norm', 'entity_aliases', ['tenant_id', 'alias_norm'], unique=False)
    op.create_table('escalations',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('tenant_id', sa.String(length=64), server_default='default', nullable=False),
    sa.Column('answer_id', sa.BigInteger(), nullable=True),
    sa.Column('question', sa.Text(), nullable=False),
    sa.Column('client', sa.Text(), nullable=True),
    sa.Column('asked_by', sa.Text(), nullable=False),
    sa.Column('routed_to_role', sa.Text(), nullable=False),
    sa.Column('assignee', sa.Text(), nullable=True),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('found', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('expert_reply', sa.Text(), nullable=True),
    sa.Column('expert_id', sa.Text(), nullable=True),
    sa.Column('episode_id', sa.String(length=40), nullable=True),
    sa.Column('resulting_fact_ids', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('answered_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['answer_id'], ['answers_log.id'], ),
    sa.ForeignKeyConstraint(['episode_id'], ['episodes.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('plugin_bindings',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('tenant_id', sa.String(length=64), server_default='default', nullable=False),
    sa.Column('plugin', sa.String(length=64), nullable=False),
    sa.Column('param', sa.Text(), nullable=False),
    sa.Column('attribute_key', sa.Text(), nullable=True),
    sa.Column('subject_entity_id', sa.String(length=40), nullable=True),
    sa.Column('confidence', sa.Float(), nullable=True),
    sa.Column('confirmed_by', sa.Text(), nullable=True),
    sa.Column('meta', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['subject_entity_id'], ['entities.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'plugin', 'param', name='uq_binding')
    )
    op.create_table('sources',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('tenant_id', sa.String(length=64), server_default='default', nullable=False),
    sa.Column('episode_id', sa.String(length=40), nullable=False),
    sa.Column('ordinal', sa.Integer(), server_default='0', nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('short_label', sa.Text(), nullable=False),
    sa.Column('part_label', sa.Text(), nullable=True),
    sa.Column('doc_type', sa.String(length=64), server_default='other', nullable=False),
    sa.Column('version', sa.String(length=32), nullable=True),
    sa.Column('dated', sa.Date(), nullable=True),
    sa.Column('valid_until', sa.Date(), nullable=True),
    sa.Column('status', sa.String(length=32), server_default='current', nullable=False),
    sa.Column('status_note', sa.Text(), nullable=True),
    sa.Column('owner', sa.Text(), nullable=True),
    sa.Column('client_scope', sa.Text(), server_default='all', nullable=False),
    sa.Column('authority_rank', sa.Integer(), nullable=True),
    sa.Column('supersedes_source_id', sa.String(length=40), nullable=True),
    sa.Column('meta', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('meta_provenance', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('confirmed_by', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['episode_id'], ['episodes.id'], ),
    sa.ForeignKeyConstraint(['supersedes_source_id'], ['sources.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_sources_episode_id'), 'sources', ['episode_id'], unique=False)
    op.create_table('passages',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('tenant_id', sa.String(length=64), server_default='default', nullable=False),
    sa.Column('source_id', sa.String(length=40), nullable=False),
    sa.Column('episode_id', sa.String(length=40), nullable=False),
    sa.Column('parent_id', sa.String(length=40), nullable=True),
    sa.Column('ordinal', sa.Integer(), nullable=False),
    sa.Column('segment_kind', sa.String(length=32), nullable=False),
    sa.Column('locator', sa.Text(), nullable=False),
    sa.Column('heading_path', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('section_title', sa.Text(), nullable=True),
    sa.Column('speaker', sa.Text(), nullable=True),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('context_header', sa.Text(), nullable=False),
    sa.Column('position', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('client_scope', sa.Text(), server_default='all', nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('retired_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('meta', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('tsv', postgresql.TSVECTOR(), sa.Computed("setweight(to_tsvector('english', coalesce(section_title, '')), 'A') || setweight(to_tsvector('english', context_header), 'B') || setweight(to_tsvector('english', text), 'D')", persisted=True), nullable=False),
    sa.Column('embedding', pgvector.sqlalchemy.vector.VECTOR(dim=384), nullable=True),
    sa.ForeignKeyConstraint(['episode_id'], ['episodes.id'], ),
    sa.ForeignKeyConstraint(['parent_id'], ['passages.id'], ),
    sa.ForeignKeyConstraint(['source_id'], ['sources.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_passages_episode_id'), 'passages', ['episode_id'], unique=False)
    op.create_index(op.f('ix_passages_source_id'), 'passages', ['source_id'], unique=False)
    op.create_index('ix_passages_source_locator', 'passages', ['source_id', 'locator'], unique=False)
    op.create_index('ix_passages_tsv', 'passages', ['tsv'], unique=False, postgresql_using='gin')
    op.create_table('facts',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('tenant_id', sa.String(length=64), server_default='default', nullable=False),
    sa.Column('origin_key', sa.Text(), nullable=False),
    sa.Column('subject_id', sa.String(length=40), nullable=False),
    sa.Column('attribute', sa.Text(), nullable=False),
    sa.Column('object_id', sa.String(length=40), nullable=True),
    sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('scope', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('condition', sa.Text(), nullable=True),
    sa.Column('statement', sa.Text(), nullable=False),
    sa.Column('quote', sa.Text(), nullable=True),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('passage_id', sa.String(length=40), nullable=True),
    sa.Column('episode_id', sa.String(length=40), nullable=True),
    sa.Column('source_id', sa.String(length=40), nullable=True),
    sa.Column('authority_rank', sa.Integer(), server_default='99', nullable=False),
    sa.Column('valid_from', sa.DateTime(timezone=True), nullable=True),
    sa.Column('valid_to', sa.DateTime(timezone=True), nullable=True),
    sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('retracted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('supersedes_id', sa.BigInteger(), nullable=True),
    sa.Column('confidence', sa.Float(), nullable=True),
    sa.Column('meta', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('embedding', pgvector.sqlalchemy.vector.VECTOR(dim=384), nullable=True),
    sa.ForeignKeyConstraint(['episode_id'], ['episodes.id'], ),
    sa.ForeignKeyConstraint(['object_id'], ['entities.id'], ),
    sa.ForeignKeyConstraint(['passage_id'], ['passages.id'], ),
    sa.ForeignKeyConstraint(['source_id'], ['sources.id'], ),
    sa.ForeignKeyConstraint(['subject_id'], ['entities.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_facts_subject_attr', 'facts', ['tenant_id', 'subject_id', 'attribute'], unique=False)
    op.create_index('uq_facts_live_origin', 'facts', ['tenant_id', 'origin_key'], unique=True, postgresql_where=sa.text('retracted_at IS NULL'))
    op.create_table('changes',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('tenant_id', sa.String(length=64), server_default='default', nullable=False),
    sa.Column('kb_version', sa.Integer(), nullable=False),
    sa.Column('new_fact', sa.BigInteger(), nullable=True),
    sa.Column('old_fact', sa.BigInteger(), nullable=True),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('effective_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('source_episode', sa.String(length=40), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['kb_version'], ['kb_versions.id'], ),
    sa.ForeignKeyConstraint(['new_fact'], ['facts.id'], ),
    sa.ForeignKeyConstraint(['old_fact'], ['facts.id'], ),
    sa.ForeignKeyConstraint(['source_episode'], ['episodes.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('conflicts',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('tenant_id', sa.String(length=64), server_default='default', nullable=False),
    sa.Column('subject_id', sa.String(length=40), nullable=True),
    sa.Column('attribute', sa.Text(), nullable=True),
    sa.Column('scope', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('fact_a', sa.BigInteger(), nullable=False),
    sa.Column('fact_b', sa.BigInteger(), nullable=False),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('authoritative_fact', sa.BigInteger(), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('detected_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['authoritative_fact'], ['facts.id'], ),
    sa.ForeignKeyConstraint(['fact_a'], ['facts.id'], ),
    sa.ForeignKeyConstraint(['fact_b'], ['facts.id'], ),
    sa.ForeignKeyConstraint(['subject_id'], ['entities.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'fact_a', 'fact_b', 'kind', name='uq_conflicts_pair')
    )
    op.create_table('acks',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('tenant_id', sa.String(length=64), server_default='default', nullable=False),
    sa.Column('change_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Text(), nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['change_id'], ['changes.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'change_id', 'user_id', name='uq_ack')
    )
    op.create_table('notifications',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('tenant_id', sa.String(length=64), server_default='default', nullable=False),
    sa.Column('user_id', sa.Text(), nullable=False),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('change_id', sa.Integer(), nullable=True),
    sa.Column('answer_id', sa.BigInteger(), nullable=True),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['answer_id'], ['answers_log.id'], ),
    sa.ForeignKeyConstraint(['change_id'], ['changes.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    for ix in ("ix_facts_valid", "ix_facts_known", "ix_passages_embedding",
               "ix_entities_embedding", "ix_facts_embedding", "ix_entities_name_trgm",
               "ix_alias_trgm"):
        op.execute(f"DROP INDEX IF EXISTS {ix}")
    op.drop_table('notifications')
    op.drop_table('acks')
    op.drop_table('conflicts')
    op.drop_table('changes')
    op.drop_index('uq_facts_live_origin', table_name='facts', postgresql_where=sa.text('retracted_at IS NULL'))
    op.drop_index('ix_facts_subject_attr', table_name='facts')
    op.drop_table('facts')
    op.drop_index('ix_passages_tsv', table_name='passages', postgresql_using='gin')
    op.drop_index('ix_passages_source_locator', table_name='passages')
    op.drop_index(op.f('ix_passages_source_id'), table_name='passages')
    op.drop_index(op.f('ix_passages_episode_id'), table_name='passages')
    op.drop_table('passages')
    op.drop_index(op.f('ix_sources_episode_id'), table_name='sources')
    op.drop_table('sources')
    op.drop_table('plugin_bindings')
    op.drop_table('escalations')
    op.drop_index('ix_alias_norm', table_name='entity_aliases')
    op.drop_table('entity_aliases')
    op.drop_table('schemas')
    op.drop_table('review_items')
    op.drop_table('kb_versions')
    op.drop_index('ix_jobs_claim', table_name='jobs')
    op.drop_table('jobs')
    op.drop_table('episodes')
    op.drop_index('ix_entities_tenant_type', table_name='entities')
    op.drop_table('entities')
    op.drop_table('answers_log')
    # ### end Alembic commands ###
