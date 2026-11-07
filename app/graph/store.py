"""Load passages for extraction and persist resolved claims. Idempotent; never deletes claims."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, aliased

from app.core.models import Claim, Conflict, KbVersion, Passage
from app.core.pack import Pack
from app.graph.extract import PassageForExtraction, extract_passage
from app.graph.schema import ClaimRec, ResolveResult

# Fields that resolution or extraction may change between builds.
_TRACKED = (
    "topic",
    "parameter",
    "scope",
    "value",
    "condition",
    "statement",
    "kind",
    "passage_id",
    "source_id",
    "authority_rank",
    "valid_at",
    "invalid_at",
    "status",
    "meta",
)


@dataclass
class PersistReport:
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    retired: int = 0
    conflicts: int = 0
    kb_version: int | None = None


def load_passages(session: Session) -> list[PassageForExtraction]:
    """Leaf passages only: a parent (a section with subsections, a desk-instruction part)
    repeats its children's text and would double every claim."""
    child = aliased(Passage)
    has_child = select(child.id).where(child.parent_id == Passage.id).exists()
    rows = session.execute(
        select(
            Passage.id,
            Passage.source_id,
            Passage.locator,
            Passage.segment_kind,
            Passage.context_header,
            Passage.text,
        )
        .where(Passage.source_id.is_not(None), ~has_child)
        .order_by(Passage.source_id, Passage.ordinal)
    ).all()
    return [PassageForExtraction(*r) for r in rows]


def extract_all(
    passages: list[PassageForExtraction],
    pack: Pack,
    structured_fn: Callable[..., Any] | None = None,
    on_progress: Callable[[int, int, PassageForExtraction], None] | None = None,
) -> list[ClaimRec]:
    claims: list[ClaimRec] = []
    for i, p in enumerate(passages, 1):
        claims.extend(extract_passage(p, pack, structured_fn))
        if on_progress:
            on_progress(i, len(passages), p)
    return claims


def _row_values(c: ClaimRec) -> dict[str, Any]:
    return {
        "origin_key": c.key,
        "topic": c.topic,
        "parameter": c.parameter,
        "scope": c.scope,
        "value": c.value,
        "condition": c.condition,
        "statement": c.statement,
        "kind": c.kind,
        "passage_id": c.passage_id,
        "source_id": c.source_id,
        "authority_rank": c.authority_rank,
        "valid_at": c.valid_at,
        "invalid_at": c.invalid_at,
        "status": c.status,
        "meta": {**c.meta, "resolution": c.reason},
    }


def current_kb_version(session: Session) -> int:
    return session.scalar(select(func.coalesce(func.max(KbVersion.id), 0))) or 0


def persist(session: Session, result: ResolveResult, now: datetime | None = None) -> PersistReport:
    """Write a resolution result in one transaction (the caller's session_scope)."""
    now = now or datetime.now(UTC)
    report = PersistReport()
    existing = {
        c.origin_key: c for c in session.scalars(select(Claim).where(Claim.origin_key.is_not(None)))
    }

    for c in result.claims:
        values = _row_values(c)
        row = existing.get(c.key)
        if row is None:
            values["expired_at"] = now if c.status == "superseded" else None
            session.add(Claim(**values))
            report.inserted += 1
            continue
        changed = {k: values[k] for k in _TRACKED if getattr(row, k) != values[k]}
        if row.expired_at is not None and row.meta.get("retired"):
            changed["expired_at"] = None  # extracted again: un-retire
        if c.status == "superseded" and row.expired_at is None:
            changed["expired_at"] = now
        elif (
            c.status != "superseded" and row.expired_at is not None and not row.meta.get("retired")
        ):
            changed["expired_at"] = None
        if changed:
            for k, v in changed.items():
                setattr(row, k, v)
            report.updated += 1
        else:
            report.unchanged += 1
    session.flush()

    # Corpus claims that are no longer extracted are retired, never deleted.
    keys = {c.key for c in result.claims}
    for key, row in existing.items():
        if key not in keys and row.meta.get("origin") == "corpus" and not row.meta.get("retired"):
            row.expired_at = now
            row.meta = {**row.meta, "retired": True, "retired_reason": "no longer in the corpus"}
            report.retired += 1
    session.flush()

    ids = dict(
        session.execute(select(Claim.origin_key, Claim.id).where(Claim.origin_key.in_(keys))).all()
    )
    for c in result.claims:
        target = ids.get(c.supersedes_key) if c.supersedes_key else None
        row_id = ids[c.key]
        session.execute(
            text(
                "UPDATE claims SET supersedes_id = :t "
                "WHERE id = :id AND supersedes_id IS DISTINCT FROM :t"
            ),
            {"t": target, "id": row_id},
        )

    for k in result.conflicts:
        stmt = (
            insert(Conflict)
            .values(
                topic=k.topic,
                parameter=k.parameter,
                scope={"client": k.client},
                claim_a=ids[k.a_key],
                claim_b=ids[k.b_key],
                kind=k.kind,
                authoritative_claim=ids.get(k.authoritative_key) if k.authoritative_key else None,
                reason=k.reason,
                status="open",
            )
            .on_conflict_do_nothing(constraint="uq_conflicts_pair")
            .returning(Conflict.id)
        )
        report.conflicts += len(session.execute(stmt).all())

    if report.inserted or report.updated or report.retired:
        counts: dict[str, int] = {}
        for c in result.claims:
            counts[c.status] = counts.get(c.status, 0) + 1
        summary = "graph build: " + ", ".join(f"{v} {k}" for k, v in sorted(counts.items()))
        version = KbVersion(summary=summary)
        session.add(version)
        session.flush()
        report.kb_version = version.id
    else:
        report.kb_version = current_kb_version(session)
    return report
