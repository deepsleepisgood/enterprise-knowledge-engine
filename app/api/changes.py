"""Change feed, acknowledgements, version and health."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from datetime import date
from typing import Any

import anyio
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import not_found, read_session, write_session
from app.core.db import session_scope
from app.distribute import feed
from app.distribute.digest import build_digest, local_today
from app.distribute.document_edit import EditNotNeeded, draft_document_edit
from app.store import answers as astore
from app.store import episodes as estore
from app.store import kb
from app.store.base import tenant, use_tenant

router = APIRouter(tags=["changes"])


@router.get("/changes")
def changes(
    since: int = 0,
    limit: int = 100,
    user_id: str | None = None,
    s: Session = Depends(read_session),
) -> list[dict]:
    """Published changes after kb_version `since`, newest first: what changed, from what to
    what, from when, and how many people have acknowledged it. With `user_id`, each item's
    `seen` says whether that user has (so "Got it" stays done after a reload)."""
    rows = kb.changes_since(s, since, limit=min(max(limit, 1), 500))
    return feed.change_items(s, rows, user_id)


@router.get("/digest")
def digest(
    day: date | None = None,
    utc_offset_minutes: int = 0,
    user_id: str | None = None,
    s: Session = Depends(read_session),
) -> dict[str, Any]:
    """One day's changes in one summary (local day: `utc_offset_minutes` east of UTC), with the
    acknowledgement counts, what this user has not seen yet, and a plain-text version to paste
    into an email or chat."""
    users = astore.distinct_users(s)
    return build_digest(
        s, day or local_today(utc_offset_minutes), utc_offset_minutes, user_id, users
    )


@router.post("/changes/{change_id}/document-edit")
def document_edit(change_id: int, s: Session = Depends(read_session)) -> dict[str, Any]:
    """Draft the edit to the document still in force that states the old rule (current text,
    suggested text and a word diff). Only for confirmed changes whose old rule is still written
    in a current document; 409 otherwise."""
    try:
        return draft_document_edit(s, change_id)
    except LookupError as exc:
        raise not_found("change") from exc
    except EditNotNeeded as exc:
        raise HTTPException(409, str(exc)) from exc


class AckIn(BaseModel):
    user_id: str


@router.post("/changes/{change_id}/ack")
def ack(change_id: int, body: AckIn, s: Session = Depends(write_session)) -> dict[str, Any]:
    if kb.get_change(s, change_id) is None:
        raise not_found("change")
    kb.ack_change(s, change_id, body.user_id)
    return {"change_id": change_id, "user_id": body.user_id, "acknowledged": True}


STREAM_POLL_S = 3.0
STREAM_LIFETIME_S = 90.0  # below proxy idle limits (the tunnel cuts at 100 s); browsers reconnect


def _signal_state(tenant_id: str, user_id: str | None) -> dict[str, Any]:
    with use_tenant(tenant_id), session_scope() as s:
        return {
            "kb_version": kb.current_kb_version(s),
            "last_change": kb.last_change_id(s),
            "unread": astore.unread_count(s, user_id) if user_id else 0,
            "episodes": estore.episode_counts(s),
        }


@router.get("/stream")
async def stream(request: Request, user_id: str | None = None) -> StreamingResponse:
    """Server-sent events: a `state` event whenever the knowledge base version, the change feed,
    the user's unread notifications or the episode pipeline moves (pages refetch on it), with a
    comment line in between to keep the connection open. The stream ends after 90 s and the
    browser reconnects on its own."""
    tid = tenant()

    async def events() -> AsyncIterator[str]:
        yield "retry: 3000\n\n"
        last: dict[str, Any] | None = None
        started = time.monotonic()
        while time.monotonic() - started < STREAM_LIFETIME_S:
            if await request.is_disconnected():
                return
            try:
                cur = await anyio.to_thread.run_sync(_signal_state, tid, user_id)
            except Exception:  # the database blinked: say nothing, try again
                cur = last
            if cur is not None and cur != last:
                yield f"event: state\ndata: {json.dumps(cur, sort_keys=True)}\n\n"
                last = cur
            else:
                yield ": idle\n\n"
            await anyio.sleep(STREAM_POLL_S)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
