"""People in the loop: the owner's review queue, escalations to experts, wrong-answer reports.

A review decision is recorded with an optimistic lock (`row_version`; 409 when someone else
decided or edited the item first). Approving or rejecting a held change
(`change`) or a `retire` item takes effect through the worker job `apply_review` (app/govern).
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.answer import escalate as esc
from app.api.deps import not_found, read_session, row, write_session
from app.store import answers as astore
from app.store import jobs, kb

router = APIRouter(tags=["review"])
DECISIONS = {"approve": "approved", "reject": "rejected", "edit": "edited"}


@router.get("/review-queue")
def review_queue(
    status: str = "open", kind: str | None = None, s: Session = Depends(read_session)
) -> list[dict[str, Any]]:
    items = kb.list_review_items(s, status=status)
    return [row(i) for i in items if kind is None or i.kind == kind]


class Decision(BaseModel):
    decision: Literal["approve", "reject", "edit"]
    by: str
    row_version: int
    payload: dict[str, Any] | None = Field(default=None, description="the edited item (edit only)")


@router.post("/review/{item_id}")
def review(item_id: int, body: Decision, s: Session = Depends(write_session)) -> dict[str, Any]:
    item = kb.get_review_item(s, item_id)
    if item is None:
        raise not_found("review item")
    if body.decision == "edit" and body.payload is None:
        raise HTTPException(422, "an edit needs the edited payload")
    if item.status != "open":
        raise HTTPException(409, f"item {item_id} is already {item.status}")
    ok = kb.decide_review_item(
        s,
        item_id,
        DECISIONS[body.decision],
        body.by,
        row_version=body.row_version,
        payload=body.payload if body.decision == "edit" else None,
    )
    if not ok:
        raise HTTPException(
            409, f"item {item_id} changed since version {body.row_version}: reload it"
        )
    job = None
    if item.kind in ("change", "retire") and body.decision in ("approve", "reject"):
        job = jobs.enqueue(s, "apply_review", {"item_id": item_id})
    return {
        "id": item_id,
        "status": DECISIONS[body.decision],
        "row_version": body.row_version + 1,
        "apply_job": job,
    }


# ---------------------------------------------------------------- escalations


class EscalateIn(BaseModel):
    answer_id: int
    asked_by: str
    role: str | None = None


@router.post("/escalations", status_code=201)
def escalate(body: EscalateIn) -> dict[str, Any]:
    """Send an answered or abstained question to the role the card routes to."""
    try:
        return esc.escalate(body.answer_id, body.asked_by, role=body.role)
    except LookupError as exc:
        raise not_found("answer") from exc


@router.get("/escalations")
def escalations(
    status: str | None = "open",
    assignee: str | None = None,
    s: Session = Depends(read_session),
) -> list[dict[str, Any]]:
    """Open (or answered, or closed) escalations, oldest first; `assignee` is a role key."""
    return [row(e) for e in astore.list_escalations(s, status=status or None, role=assignee)]


class ReplyIn(BaseModel):
    expert_id: str
    text: str = Field(min_length=1, max_length=20_000)
    expert_role: str | None = None
    effective: date | None = None
    scope: str | None = None


@router.post("/escalations/{escalation_id}/reply", status_code=202)
def reply(escalation_id: int, body: ReplyIn) -> dict[str, Any]:
    """The expert's reply goes back to the asker and enters as an `expert_answer` episode. It
    changes the knowledge base only through the same extraction and governance as any input."""
    try:
        return esc.reply(
            escalation_id,
            body.expert_id,
            body.text,
            expert_role=body.expert_role,
            effective=body.effective,
            scope=body.scope,
        )
    except LookupError as exc:
        raise not_found("escalation") from exc


class CloseIn(BaseModel):
    by: str
    note: str = ""


@router.post("/escalations/{escalation_id}/close")
def close(escalation_id: int, body: CloseIn, s: Session = Depends(write_session)) -> dict:
    e = astore.get_escalation(s, escalation_id)
    if e is None:
        raise not_found("escalation")
    if e.status == "closed":
        raise HTTPException(409, "already closed")
    found = {**e.found, "closed_by": body.by, **({"close_note": body.note} if body.note else {})}
    astore.set_escalation(s, escalation_id, status="closed", found=found)
    return {"id": escalation_id, "status": "closed"}


class ReportIn(BaseModel):
    user_id: str
    note: str = ""


@router.post("/answers/{answer_id}/report", status_code=201)
def report(answer_id: int, body: ReportIn) -> dict[str, Any]:
    """ "Report a wrong answer": goes to the process owner's queue with the card attached."""
    try:
        return esc.report_wrong(answer_id, body.user_id, body.note)
    except LookupError as exc:
        raise not_found("answer") from exc
