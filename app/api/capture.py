"""Expert capture (T10): five questions, a structured entry, a rule check, a named reviewer.

    GET  /capture/questions              the questions and who can review
    POST /capture/match                  entities the "who or what" answer names
    POST /capture/check                  compatible / conflict / no rule, against the rules now
    POST /capture/entries                send an entry for review (an `expert_capture` episode)
    GET  /capture/entries                entries with their review status, and the notes the
                                         knowledge base already has
    POST /capture/entries/{id}/edit      a reviewer's edit: the original is rejected and the
                                         edited entry is sent for review in its place

Approving or rejecting an entry is the review queue's decision (`POST /review/{item_id}`).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import not_found, read_session, write_session
from app.capture import interview as cap
from app.store import episodes as estore
from app.store import jobs, kb

router = APIRouter(tags=["capture"])


class MatchIn(BaseModel):
    text: str = Field(min_length=1, max_length=200)


class CheckIn(BaseModel):
    entry: cap.Entry


class SubmitIn(BaseModel):
    entry: cap.Entry
    reviewer: str = Field(default=cap.PROCESS_OWNER, min_length=1, max_length=120)
    check: cap.RuleCheck | None = None


class EditIn(BaseModel):
    entry: cap.Entry
    by: str = Field(min_length=1, max_length=120)
    reviewer: str | None = None


@router.get("/capture/questions")
def capture_questions() -> dict[str, Any]:
    return cap.questions()


@router.post("/capture/match")
def capture_match(body: MatchIn, s: Session = Depends(read_session)) -> dict[str, Any]:
    return {"candidates": cap.match_subject(s, body.text)}


@router.post("/capture/check")
def capture_check(body: CheckIn, s: Session = Depends(read_session)) -> cap.RuleCheck:
    """Check the entry against the closest rules in force (one fast model call)."""
    return cap.check_rules(s, body.entry)


@router.post("/capture/entries", status_code=202)
def capture_submit(body: SubmitIn, s: Session = Depends(write_session)) -> dict[str, Any]:
    """Send for review. The worker parses it and opens the review item; nothing is in the
    knowledge base until the reviewer approves."""
    episode_id = cap.submit(s, body.entry, body.reviewer, body.check)
    return {"episode_id": episode_id, "status": "queued", "reviewer": body.reviewer}


@router.get("/capture/entries")
def capture_entries(s: Session = Depends(read_session)) -> dict[str, Any]:
    return {"entries": cap.entries(s), "known": cap.known_notes(s)}


@router.post("/capture/entries/{episode_id}/edit", status_code=202)
def capture_edit(
    episode_id: str, body: EditIn, s: Session = Depends(write_session)
) -> dict[str, Any]:
    ep = estore.get_episode(s, episode_id)
    if ep is None or ep.channel != cap.CHANNEL:
        raise not_found("captured entry")
    old = (ep.meta or {}).get("capture") or {}
    item = next(
        (
            i
            for i in kb.list_review_items(s, status="open")
            if i.kind == "change" and (i.payload or {}).get("episode_id") == episode_id
        ),
        None,
    )
    if item is None:
        raise HTTPException(409, "only an entry waiting for review can be edited")
    if not kb.decide_review_item(s, item.id, "rejected", body.by, row_version=item.row_version):
        raise HTTPException(409, "the entry was decided meanwhile: reload it")
    jobs.enqueue(s, "apply_review", {"item_id": item.id})
    reviewer = body.reviewer or old.get("reviewer") or cap.PROCESS_OWNER
    check = cap.RuleCheck.model_validate(old["check"]) if old.get("check") else None
    new_id = cap.submit(s, body.entry, reviewer, check, edited_from=episode_id)
    return {"episode_id": new_id, "replaces": episode_id, "status": "queued"}
