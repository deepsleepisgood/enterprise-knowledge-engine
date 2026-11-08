"""Conflict report: run the scan (as a background job) and list what it found."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import not_found, read_session, write_session
from app.graph.conflicts import value_text
from app.store import facts as fstore
from app.store import jobs, kb

router = APIRouter(tags=["conflicts"])


class ScanIn(BaseModel):
    exclude_passages: list[str] = []  # e.g. a change table that states the conflicts outright


@router.post("/conflict-scan", status_code=202)
def conflict_scan(body: ScanIn | None = None, s: Session = Depends(write_session)) -> dict:
    """Queue a full scan on the worker (it judges text values with the model, so it takes
    minutes). Poll `GET /conflicts`; the job id is returned for tracing."""
    payload = {"exclude_passages": sorted((body or ScanIn()).exclude_passages)}
    job_id = jobs.enqueue_once(s, "conflict_scan", payload)
    return {"job_id": job_id, "queued": job_id is not None}


@router.get("/conflict-scan")
def last_scan(s: Session = Depends(read_session)) -> dict[str, Any]:
    """The latest scan job: queued, running, done (with its summary) or failed."""
    j = jobs.latest(s, "conflict_scan")
    if j is None:
        return {"status": "never"}
    return {
        "job_id": j.id,
        "status": j.status,
        "queued_at": j.run_after,
        "finished_at": j.finished_at,
        "result": j.result or {},
        "error": j.error,
    }


def _side(f: Any) -> dict[str, Any] | None:
    if f is None:
        return None
    return {
        "fact_id": f.id,
        "passage_id": f.passage_id,
        "source": f.source_label,
        "locator": f.locator,
        "value": value_text(f),
        "statement": f.statement,
        "quote": f.quote,
        "status": f.status,
        "valid_from": f.valid_from,
    }


@router.get("/conflicts")
def conflicts(
    status: str | None = "open", kind: str | None = None, s: Session = Depends(read_session)
) -> list[dict[str, Any]]:
    """Each conflict with both sides (source, locator, value, statement), the authoritative
    side and the reason it holds (precedence rule and dates)."""
    rows = [c for c in kb.list_conflicts(s, status=status) if kind is None or c.kind == kind]
    facts = fstore.by_ids(s, sorted({i for c in rows for i in (c.fact_a, c.fact_b)}))
    out = []
    for c in rows:
        auth_id = c.authoritative_fact or c.fact_a
        other_id = c.fact_b if auth_id == c.fact_a else c.fact_a
        auth, other = facts.get(auth_id), facts.get(other_id)
        out.append(
            {
                "id": c.id,
                "kind": c.kind,
                "status": c.status,
                "attribute": c.attribute,
                "scope": c.scope,
                "topic": (auth.subject_name if auth else None) or c.attribute,
                "authoritative": _side(auth),
                "conflicting": _side(other),
                "reason": c.reason,
                "detected_at": c.detected_at,
            }
        )
    return out


class ConflictStatus(BaseModel):
    status: Literal["open", "resolved", "dismissed"]


@router.post("/conflicts/{conflict_id}")
def set_status(
    conflict_id: int, body: ConflictStatus, s: Session = Depends(write_session)
) -> dict[str, Any]:
    """The owner marks a conflict resolved (the outdated document was fixed) or dismissed."""
    if kb.get_conflict(s, conflict_id) is None:
        raise not_found("conflict")
    if not kb.set_conflict_status(s, conflict_id, body.status):
        raise HTTPException(409, "conflict changed meanwhile")
    return {"id": conflict_id, "status": body.status}


class ToReview(BaseModel):
    by: str


@router.post("/conflicts/{conflict_id}/review", status_code=201)
def open_in_review(
    conflict_id: int, body: ToReview, s: Session = Depends(write_session)
) -> dict[str, Any]:
    """Put a conflict on the owner's review queue (for example to fix the outdated document)."""
    c = kb.get_conflict(s, conflict_id)
    if c is None:
        raise not_found("conflict")
    facts = fstore.by_ids(s, [c.fact_a, c.fact_b])
    auth_id = c.authoritative_fact or c.fact_a
    other_id = c.fact_b if auth_id == c.fact_a else c.fact_a
    item = kb.add_review_item(
        s,
        "conflict",
        jsonable_encoder(
            {
                "conflict_id": c.id,
                "summary": f"Conflict on {c.attribute}: {c.reason}",
                "authoritative": _side(facts.get(auth_id)),
                "conflicting": _side(facts.get(other_id)),
                "opened_by": body.by,
            }
        ),
    )
    return {"review_item": item}
