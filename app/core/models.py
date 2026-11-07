"""Database schema (SQLAlchemy 2). The Alembic migration in migrations/versions mirrors this."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
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
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

EMBEDDING_DIM = 384

# Section title weighs most (A), then the context header (B), then the body (D).
TSV_EXPRESSION = (
    "setweight(to_tsvector('english', coalesce(section_title, '')), 'A') || "
    "setweight(to_tsvector('english', context_header), 'B') || "
    "setweight(to_tsvector('english', text), 'D')"
)


class Base(DeclarativeBase):
    pass


def _now() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Source(Base):
    """One document or document part (one row per source_index entry)."""

    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # pack key, e.g. "sop_v4"
    file: Mapped[str] = mapped_column(Text, nullable=False)
    part: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)  # short UI label, e.g. "SOP v4.0"
    version: Mapped[str | None] = mapped_column(String(32))
    dated: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    status_note: Mapped[str | None] = mapped_column(Text)
    owner: Mapped[str | None] = mapped_column(Text)
    authority_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    client_scope: Mapped[str] = mapped_column(String(32), nullable=False, default="all")
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = _now()


class Episode(Base):
    """A raw incoming message (email, chat) before triage."""

    __tablename__ = "episodes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    source_uri: Mapped[str | None] = mapped_column(Text)
    sender: Mapped[str | None] = mapped_column(Text)
    sender_role: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_hint: Mapped[str | None] = mapped_column(Text)
    scope_hint: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    triage_label: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="received")
    created_at: Mapped[datetime] = _now()


class Passage(Base):
    """A cited unit of text: an SOP section, a desk-instruction step, a transcript turn."""

    __tablename__ = "passages"
    __table_args__ = (
        Index("ix_passages_tsv", "tsv", postgresql_using="gin"),
        Index("ix_passages_source_locator", "source_id", "locator"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # stable content-free hash
    source_id: Mapped[str | None] = mapped_column(ForeignKey("sources.id"))
    episode_id: Mapped[int | None] = mapped_column(ForeignKey("episodes.id"))
    parent_id: Mapped[str | None] = mapped_column(String(32))
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    segment_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    locator: Mapped[str] = mapped_column(Text, nullable=False)
    heading_path: Mapped[str] = mapped_column(Text, nullable=False)
    section_title: Mapped[str | None] = mapped_column(Text)
    speaker: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    context_header: Mapped[str] = mapped_column(Text, nullable=False)
    client_scope: Mapped[str] = mapped_column(String(32), nullable=False, default="all")
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    source_status: Mapped[str] = mapped_column(String(32), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    tsv: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed(TSV_EXPRESSION, persisted=True),
    )
    embedding: Mapped[Any | None] = mapped_column(Vector(EMBEDDING_DIM))
    created_at: Mapped[datetime] = _now()


class Claim(Base):
    """A typed rule-claim extracted from a passage; never deleted, only retired."""

    __tablename__ = "claims"
    __table_args__ = (
        Index("ix_claims_topic_param", "topic", "parameter"),
        UniqueConstraint("origin_key", name="uq_claims_origin_key"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    topic: Mapped[str] = mapped_column(String(64), nullable=False)
    parameter: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    condition: Mapped[str | None] = mapped_column(Text)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    passage_id: Mapped[str | None] = mapped_column(ForeignKey("passages.id"))
    source_id: Mapped[str | None] = mapped_column(ForeignKey("sources.id"))
    authority_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    valid_at: Mapped[date | None] = mapped_column(Date)
    invalid_at: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = _now()
    expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    supersedes_id: Mapped[int | None] = mapped_column(ForeignKey("claims.id"))
    # Stable key for claims extracted from the corpus (hash of passage, prompt version and
    # claim content), so a rebuild updates rows in place. Null for claims from intake.
    origin_key: Mapped[str | None] = mapped_column(String(40))
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class Conflict(Base):
    __tablename__ = "conflicts"
    __table_args__ = (UniqueConstraint("claim_a", "claim_b", "kind", name="uq_conflicts_pair"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    topic: Mapped[str] = mapped_column(String(64), nullable=False)
    parameter: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    claim_a: Mapped[int] = mapped_column(ForeignKey("claims.id"), nullable=False)
    claim_b: Mapped[int] = mapped_column(ForeignKey("claims.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    authoritative_claim: Mapped[int | None] = mapped_column(ForeignKey("claims.id"))
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    detected_at: Mapped[datetime] = _now()


class ReviewItem(Base):
    __tablename__ = "review_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    risk_tier: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    decided_by: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()


class KbVersion(Base):
    __tablename__ = "kb_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    published_at: Mapped[datetime] = _now()
    summary: Mapped[str] = mapped_column(Text, nullable=False)


class Change(Base):
    __tablename__ = "changes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kb_version: Mapped[int] = mapped_column(ForeignKey("kb_versions.id"), nullable=False)
    new_claim: Mapped[int | None] = mapped_column(ForeignKey("claims.id"))
    old_claim: Mapped[int | None] = mapped_column(ForeignKey("claims.id"))
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    effective_at: Mapped[date | None] = mapped_column(Date)
    source_episode: Mapped[int | None] = mapped_column(ForeignKey("episodes.id"))
    created_at: Mapped[datetime] = _now()


class AnswerLog(Base):
    __tablename__ = "answers_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    client: Mapped[str | None] = mapped_column(String(32))
    kb_version: Mapped[int] = mapped_column(Integer, nullable=False)
    route: Mapped[str] = mapped_column(String(64), nullable=False)
    card: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    cited_claim_ids: Mapped[list[int]] = mapped_column(JSONB, nullable=False, default=list)
    cited_passage_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = _now()


class Ack(Base):
    __tablename__ = "acks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    change_id: Mapped[int] = mapped_column(ForeignKey("changes.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    at: Mapped[datetime] = _now()


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    change_id: Mapped[int | None] = mapped_column(ForeignKey("changes.id"))
    answer_id: Mapped[int | None] = mapped_column(ForeignKey("answers_log.id"))
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    at: Mapped[datetime] = _now()
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TacitEntry(Base):
    __tablename__ = "tacit_entries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    vendor_id: Mapped[str | None] = mapped_column(String(32))
    scope: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    habit: Mapped[str] = mapped_column(Text, nullable=False)
    trigger: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[str | None] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(Text)
    reviewer: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    created_at: Mapped[datetime] = _now()


class Vendor(Base):
    """Supplier master. Deliberately has no PAN or bank fields."""

    __tablename__ = "vendors"

    vendor_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    primary_client: Mapped[str | None] = mapped_column(String(32))
    state: Mapped[str | None] = mapped_column(Text)
    msme_category: Mapped[str | None] = mapped_column(String(16))
    supply_type: Mapped[str | None] = mapped_column(Text)
    aato_crore: Mapped[float | None] = mapped_column(Float)
    einvoice_required: Mapped[bool | None] = mapped_column(Boolean)
    qrmp_filer: Mapped[bool | None] = mapped_column(Boolean)
    default_tds_section: Mapped[str | None] = mapped_column(String(16))
    payment_term_days: Mapped[int | None] = mapped_column(Integer)
    written_term_agreement: Mapped[bool | None] = mapped_column(Boolean)
    habit_note: Mapped[str | None] = mapped_column(Text)
