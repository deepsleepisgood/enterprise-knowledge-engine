"""Change feed, acknowledgements, version and health."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import not_found, read_session, write_session
from app.core.db import session_scope
from app.graph.conflicts import value_text
from app.store import facts as fstore
from app.store import kb

router = APIRouter(tags=["changes"])
PROVISIONAL = {"pending", "provisional"}


@router.get("/changes")
def changes(since: int = 0, limit: int = 100, s: Session = Depends(read_session)) -> list[dict]:
    """Published changes after kb_version `since`, newest first: what changed, from what to
    what, from when, and how many people have acknowledged it."""
    rows = kb.changes_since(s, since, limit=min(max(limit, 1), 500))
    fact_ids = sorted({i for c in rows for i in (c.new_fact, c.old_fact) if i})
    facts = fstore.by_ids(s, fact_ids)
    acks = kb.ack_counts(s, [c.id for c in rows])
    out = []
    for c in rows:
        new, old = facts.get(c.new_fact or -1), facts.get(c.old_fact or -1)
        ref = new or old
        if new is None:
            status = "rejected" if old is not None else "confirmed"
        elif new.retracted_at is not None:
            status = "rejected"
        else:
            status = "provisional" if new.status in PROVISIONAL else "confirmed"
        out.append(
            {
                "id": c.id,
                "kb_version": c.kb_version,
                "summary": c.summary,
                "topic": (ref.subject_name or ref.attribute) if ref else "",
                "attribute": ref.attribute if ref else None,
                "old_value": value_text(old) if old else "",
                "new_value": value_text(new) if new else "",
                "effective_at": c.effective_at or c.created_at,
                "status": status,
                "source_label": (new.source_label if new else None) or "",
                "acknowledged": acks.get(c.id, 0),
            }
        )
    return out


class AckIn(BaseModel):
    user_id: str


@router.post("/changes/{change_id}/ack")
def ack(change_id: int, body: AckIn, s: Session = Depends(write_session)) -> dict[str, Any]:
    if kb.get_change(s, change_id) is None:
        raise not_found("change")
    kb.ack_change(s, change_id, body.user_id)
    return {"change_id": change_id, "user_id": body.user_id, "acknowledged": True}


@router.get("/version")
def version(s: Session = Depends(read_session)) -> dict[str, Any]:
    sc = kb.active_schema(s)
    return {
        "kb_version": kb.current_kb_version(s),
        "schema_version": sc.version if sc is not None and sc.status == "frozen" else None,
    }


@router.get("/health", response_model=None)
def health() -> dict[str, Any] | JSONResponse:
    try:
        with session_scope() as s:
            ok = kb.ping(s)
    except Exception as exc:  # report, never raise: load balancers poll this
        return JSONResponse({"status": "down", "db": False, "error": type(exc).__name__}, 503)
    return {"status": "ok", "db": ok}
