"""Postgres job queue: enqueue, claim with FOR UPDATE SKIP LOCKED, finish, retry with backoff."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from app.store.base import tenant, utcnow
from app.store.models import Job

BACKOFF_S = (5, 30, 120)


@dataclass
class ClaimedJob:
    id: int
    tenant_id: str
    kind: str
    payload: dict[str, Any]
    attempts: int
    max_attempts: int


def enqueue(session: Session, kind: str, payload: dict[str, Any], max_attempts: int = 3) -> int:
    job = Job(tenant_id=tenant(), kind=kind, payload=payload, max_attempts=max_attempts)
    session.add(job)
    session.flush()
    return job.id


def enqueue_once(session: Session, kind: str, payload: dict[str, Any]) -> int | None:
    """Queue a job unless one of the same kind is already waiting (for idempotent work)."""
    waiting = session.scalar(
        select(Job.id).where(Job.tenant_id == tenant(), Job.kind == kind, Job.status == "queued")
    )
    return None if waiting else enqueue(session, kind, payload)


_CLAIM = text(
    """
    UPDATE jobs SET status = 'running', locked_by = :worker, locked_at = now(),
                    attempts = attempts + 1
    WHERE id = (
        SELECT id FROM jobs
        WHERE status = 'queued' AND run_after <= now()
          AND (CAST(:kinds AS text[]) IS NULL OR kind = ANY(CAST(:kinds AS text[])))
        ORDER BY id
        FOR UPDATE SKIP LOCKED
        LIMIT 1
    )
    RETURNING id, tenant_id, kind, payload, attempts, max_attempts
    """
)


def claim(session: Session, worker: str, kinds: list[str] | None = None) -> ClaimedJob | None:
    row = session.execute(_CLAIM, {"worker": worker, "kinds": kinds}).first()
    return ClaimedJob(*row) if row else None


def complete(session: Session, job_id: int, result: dict[str, Any] | None = None) -> None:
    session.execute(
        update(Job)
        .where(Job.id == job_id)
        .values(status="done", result=result or {}, finished_at=func.now(), error=None)
    )


def fail(session: Session, job: ClaimedJob, error: str) -> str:
    """Retry with backoff while attempts remain; otherwise mark failed. Returns the status."""
    if job.attempts < job.max_attempts:
        delay = BACKOFF_S[min(job.attempts - 1, len(BACKOFF_S) - 1)]
        values = {"status": "queued", "run_after": utcnow() + timedelta(seconds=delay)}
    else:
        values = {"status": "failed", "finished_at": utcnow()}
    session.execute(
        update(Job).where(Job.id == job.id).values(error=error[:4000], locked_by=None, **values)
    )
    return values["status"]


def requeue_stale(session: Session, older_than_s: int = 900) -> int:
    """Jobs left 'running' by a killed worker go back to the queue."""
    cutoff = utcnow() - timedelta(seconds=older_than_s)
    res = session.execute(
        update(Job)
        .where(Job.status == "running", Job.locked_at < cutoff)
        .values(status="queued", locked_by=None)
    )
    return res.rowcount or 0


def counts(session: Session) -> dict[str, int]:
    rows = session.execute(
        select(Job.status, func.count()).where(Job.tenant_id == tenant()).group_by(Job.status)
    )
    return {s: n for s, n in rows}


def failed_jobs(session: Session, limit: int = 50) -> list[Job]:
    q = (
        select(Job)
        .where(Job.tenant_id == tenant(), Job.status == "failed")
        .order_by(Job.id.desc())
        .limit(limit)
    )
    return list(session.scalars(q))
