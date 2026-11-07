"""Database schema (SQLAlchemy 2). Only `app/store/` may import this module (CLAUDE.md rule 11).

The Alembic migration in migrations/versions mirrors these tables. Every table has `tenant_id`.

Facts are bitemporal. Valid time is the half-open interval [valid_from, valid_to): when the fact
was true in the world. Transaction time is [recorded_at, retracted_at): when the engine believed
this row. A row is never edited after it is written, apart from closing `retracted_at`; a change
of belief retracts the row and inserts a new version with the same `origin_key`.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Computed,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

EMBEDDING_DIM = 384
DEFAULT_TENANT = "default"

# Section title weighs most (A), then the context header (B), then the body (D).
TSV_EXPRESSION = (
    "setweight(to_tsvector('english', coalesce(section_title, '')), 'A') || "
    "setweight(to_tsvector('english', context_header), 'B') || "
    "setweight(to_tsvector('english', text), 'D')"
)


class Base(DeclarativeBase):
    pass


def _tenant() -> Mapped[str]:
    return mapped_column(
        String(64), nullable=False, default=DEFAULT_TENANT, server_default=DEFAULT_TENANT
    )


def _now() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def _json(default: str = "{}") -> Mapped[Any]:
    return mapped_column(JSONB, nullable=False, server_default=text(f"'{default}'::jsonb"))


class Episode(Base):
    """One raw unit of input (a file, a file version, an email, a message). Never deleted."""

    __tablename__ = "episodes"
    __table_args__ = (UniqueConstraint("tenant_id", "content_hash", name="uq_episodes_hash"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    tenant_id: Mapped[str] = _tenant()
    channel: Mapped[str] = mapped_column(String(32), nullable=False)  # upload, api, email, ...
    source_uri: Mapped[str | None] = mapped_column(Text)  # original file name or path
    blob_path: Mapped[str | None] = mapped_column(Text)  # the original, as received
    mime: Mapped[str | None] = mapped_column(String(128))
    sender: Mapped[str | None] = mapped_column(Text)
    sender_role: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_hint: Mapped[date | None] = mapped_column(Date)
    scope_hint: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    parse_tier: Mapped[int | None] = mapped_column(Integer)
    parse_quality: Mapped[float | None] = mapped_column(Float)
    triage_label: Mapped[str | None] = mapped_column(String(32))
    # queued, parsed, extracted, published, pending_review, needs_attention, failed
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    error: Mapped[str | None] = mapped_column(Text)
    confirmations: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    meta: Mapped[dict[str, Any]] = _json()
    created_at: Mapped[datetime] = _now()


class Source(Base):
    """One document inside an episode. A file can hold several (a pack of memos)."""

    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    tenant_id: Mapped[str] = _tenant()
    episode_id: Mapped[str] = mapped_column(ForeignKey("episodes.id"), nullable=False, index=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    title: Mapped[str] = mapped_column(Text, nullable=False)
    short_label: Mapped[str] = mapped_column(Text, nullable=False)  # "SOP v4.0", "CM-INF-02"
    part_label: Mapped[str | None] = mapped_column(Text)  # "Part C", "Video 1" when in a pack
    doc_type: Mapped[str] = mapped_column(String(64), nullable=False, server_default="other")
    version: Mapped[str | None] = mapped_column(String(32))
    dated: Mapped[date | None] = mapped_column(Date)  # effective or document date
    valid_until: Mapped[date | None] = mapped_column(Date)  # last day in force, inclusive
    # current, superseded, draft, outdated, record (observation or interview), unknown
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="current")
    status_note: Mapped[str | None] = mapped_column(Text)
    owner: Mapped[str | None] = mapped_column(Text)
    client_scope: Mapped[str] = mapped_column(Text, nullable=False, server_default="all")
    authority_rank: Mapped[int | None] = mapped_column(Integer)
    supersedes_source_id: Mapped[str | None] = mapped_column(ForeignKey("sources.id"))
    meta: Mapped[dict[str, Any]] = _json()  # raw header key-values, origin of each field
    meta_provenance: Mapped[dict[str, Any]] = _json()  # field -> {origin, confidence}
    confirmed_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()


class Passage(Base):
    """A structure-aware chunk of a source, with a locator so it can be cited."""

    __tablename__ = "passages"
    __table_args__ = (
        Index("ix_passages_tsv", "tsv", postgresql_using="gin"),
        Index("ix_passages_source_locator", "source_id", "locator"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    tenant_id: Mapped[str] = _tenant()
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), nullable=False, index=True)
    episode_id: Mapped[str] = mapped_column(ForeignKey("episodes.id"), nullable=False, index=True)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("passages.id"))
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    # section, step, table, table_row, turn, note, slide, message, record, window, preamble
    segment_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    locator: Mapped[str] = mapped_column(Text, nullable=False)
    heading_path: Mapped[list[str]] = _json("[]")
    section_title: Mapped[str | None] = mapped_column(Text)
    speaker: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    context_header: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[dict[str, Any]] = _json()  # page, bbox, cells, slide, offsets, time
    client_scope: Mapped[str] = mapped_column(Text, nullable=False, server_default="all")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    meta: Mapped[dict[str, Any]] = _json()
    tsv: Mapped[Any] = mapped_column(TSVECTOR, Computed(TSV_EXPRESSION, persisted=True))
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))


class Schema(Base):
    """An ontology: induced from the corpus (or a plug-in baseline), edited and frozen."""

    __tablename__ = "schemas"
    __table_args__ = (UniqueConstraint("tenant_id", "version", name="uq_schemas_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = _tenant()
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="induced")
    ontology: Mapped[dict[str, Any]] = _json()
    sample: Mapped[list[Any]] = _json("[]")  # passage ids the induction looked at
    created_at: Mapped[datetime] = _now()
    frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    frozen_by: Mapped[str | None] = mapped_column(Text)


class Entity(Base):
    __tablename__ = "entities"
    __table_args__ = (Index("ix_entities_tenant_type", "tenant_id", "type"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    tenant_id: Mapped[str] = _tenant()
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    attrs: Mapped[dict[str, Any]] = _json()
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    merged_into: Mapped[str | None] = mapped_column(ForeignKey("entities.id"))
    created_at: Mapped[datetime] = _now()


class EntityAlias(Base):
    __tablename__ = "entity_aliases"
    __table_args__ = (
        UniqueConstraint("tenant_id", "entity_id", "alias_norm", name="uq_alias"),
        Index("ix_alias_norm", "tenant_id", "alias_norm"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = _tenant()
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), nullable=False)
    alias: Mapped[str] = mapped_column(Text, nullable=False)
    alias_norm: Mapped[str] = mapped_column(Text, nullable=False)
    episode_id: Mapped[str | None] = mapped_column(ForeignKey("episodes.id"))
    created_at: Mapped[datetime] = _now()


class Fact(Base):
    """A bitemporal fact edge: (subject) -[attribute]-> value or object, within a scope."""

    __tablename__ = "facts"
    __table_args__ = (
        Index("ix_facts_subject_attr", "tenant_id", "subject_id", "attribute"),
        Index(
            "uq_facts_live_origin",
            "tenant_id",
            "origin_key",
            unique=True,
            postgresql_where=text("retracted_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = _tenant()
    origin_key: Mapped[str] = mapped_column(Text, nullable=False)  # passage + claim + prompt
    subject_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), nullable=False)
    attribute: Mapped[str] = mapped_column(Text, nullable=False)
    object_id: Mapped[str | None] = mapped_column(ForeignKey("entities.id"))
    value: Mapped[dict[str, Any]] = _json()  # {type, number, unit, text, date, items}
    scope: Mapped[dict[str, Any]] = _json()  # {client, materials, ...}; client entity name
    condition: Mapped[str | None] = mapped_column(Text)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    quote: Mapped[str | None] = mapped_column(Text)
    # rule, practice, definition, procedure, attribute
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    passage_id: Mapped[str | None] = mapped_column(ForeignKey("passages.id"))
    episode_id: Mapped[str | None] = mapped_column(ForeignKey("episodes.id"))
    source_id: Mapped[str | None] = mapped_column(ForeignKey("sources.id"))
    authority_rank: Mapped[int] = mapped_column(Integer, nullable=False, server_default="99")
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # current, superseded, overridden, corroborating, provisional, pending, rejected
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    supersedes_id: Mapped[int | None] = mapped_column(BigInteger)
    confidence: Mapped[float | None] = mapped_column(Float)
    meta: Mapped[dict[str, Any]] = _json()
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))


class PluginBinding(Base):
    __tablename__ = "plugin_bindings"
    __table_args__ = (UniqueConstraint("tenant_id", "plugin", "param", name="uq_binding"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = _tenant()
    plugin: Mapped[str] = mapped_column(String(64), nullable=False)
    param: Mapped[str] = mapped_column(Text, nullable=False)
    attribute_key: Mapped[str | None] = mapped_column(Text)
    subject_entity_id: Mapped[str | None] = mapped_column(ForeignKey("entities.id"))
    confidence: Mapped[float | None] = mapped_column(Float)
    confirmed_by: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict[str, Any]] = _json()
    updated_at: Mapped[datetime] = _now()


class Conflict(Base):
    __tablename__ = "conflicts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "fact_a", "fact_b", "kind", name="uq_conflicts_pair"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = _tenant()
    subject_id: Mapped[str | None] = mapped_column(ForeignKey("entities.id"))
    attribute: Mapped[str | None] = mapped_column(Text)
    scope: Mapped[dict[str, Any]] = _json()
    fact_a: Mapped[int] = mapped_column(ForeignKey("facts.id"), nullable=False)
    fact_b: Mapped[int] = mapped_column(ForeignKey("facts.id"), nullable=False)
    # value, scope, self_contradiction, practice_vs_rule
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    authoritative_fact: Mapped[int | None] = mapped_column(ForeignKey("facts.id"))
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    detected_at: Mapped[datetime] = _now()


class ReviewItem(Base):
    __tablename__ = "review_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = _tenant()
    # change, conflict, tacit, schema, metadata, question, report, retire
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any]] = _json()
    risk_tier: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    decided_by: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()


class KbVersion(Base):
    __tablename__ = "kb_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = _tenant()
    published_at: Mapped[datetime] = _now()
    summary: Mapped[str] = mapped_column(Text, nullable=False)


class Change(Base):
    __tablename__ = "changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = _tenant()
    kb_version: Mapped[int] = mapped_column(ForeignKey("kb_versions.id"), nullable=False)
    new_fact: Mapped[int | None] = mapped_column(ForeignKey("facts.id"))
    old_fact: Mapped[int | None] = mapped_column(ForeignKey("facts.id"))
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_episode: Mapped[str | None] = mapped_column(ForeignKey("episodes.id"))
    created_at: Mapped[datetime] = _now()


class AnswerLog(Base):
    __tablename__ = "answers_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = _tenant()
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    client: Mapped[str | None] = mapped_column(Text)
    as_of: Mapped[date | None] = mapped_column(Date)
    kb_version: Mapped[int] = mapped_column(Integer, nullable=False)
    route: Mapped[str] = mapped_column(String(64), nullable=False)
    card: Mapped[dict[str, Any]] = _json()
    cited_fact_ids: Mapped[list[int]] = _json("[]")
    cited_passage_ids: Mapped[list[str]] = _json("[]")
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = _now()


class Ack(Base):
    __tablename__ = "acks"
    __table_args__ = (UniqueConstraint("tenant_id", "change_id", "user_id", name="uq_ack"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = _tenant()
    change_id: Mapped[int] = mapped_column(ForeignKey("changes.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    at: Mapped[datetime] = _now()


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = _tenant()
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    change_id: Mapped[int | None] = mapped_column(ForeignKey("changes.id"))
    answer_id: Mapped[int | None] = mapped_column(ForeignKey("answers_log.id"))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    at: Mapped[datetime] = _now()
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Escalation(Base):
    __tablename__ = "escalations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = _tenant()
    answer_id: Mapped[int | None] = mapped_column(ForeignKey("answers_log.id"))
    question: Mapped[str] = mapped_column(Text, nullable=False)
    client: Mapped[str | None] = mapped_column(Text)
    asked_by: Mapped[str] = mapped_column(Text, nullable=False)
    routed_to_role: Mapped[str] = mapped_column(Text, nullable=False)
    assignee: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="question")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    found: Mapped[dict[str, Any]] = _json()  # what the engine found and why it abstained
    expert_reply: Mapped[str | None] = mapped_column(Text)
    expert_id: Mapped[str | None] = mapped_column(Text)
    episode_id: Mapped[str | None] = mapped_column(ForeignKey("episodes.id"))
    resulting_fact_ids: Mapped[list[int]] = _json("[]")
    created_at: Mapped[datetime] = _now()
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Job(Base):
    """Postgres job queue, claimed with SELECT ... FOR UPDATE SKIP LOCKED."""

    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_claim", "status", "run_after"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = _tenant()
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = _json()
    # queued, running, done, failed
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    run_after: Mapped[datetime] = _now()
    locked_by: Mapped[str | None] = mapped_column(Text)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict[str, Any]] = _json()
    created_at: Mapped[datetime] = _now()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
