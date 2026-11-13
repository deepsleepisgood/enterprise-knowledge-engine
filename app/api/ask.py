"""POST /ask: a question in, an answer card out.

POST /ask/jobs and GET /ask/jobs/{id} do the same without holding the request open: the web app
polls for the card, so a slow model never runs into a proxy's request timeout (a Cloudflare
tunnel closes requests after about 100 s)."""

from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from datetime import date, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.answer.pipeline import ask as answer
from app.api.plugins import plugin_context
from app.core.db import session_scope
from app.graph.pipeline import active_ontology
from app.store import facts as fstore
from app.store.base import norm_name

router = APIRouter(tags=["ask"])


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    user_id: str = "anonymous"
    client: str | None = None
    invoice_id: str | None = None
    as_of: date | None = None
    known_at: datetime | None = None
    viewer: Literal["processor", "owner"] = "processor"


def _known_scope(name: str | None) -> str | None:
    """An operational system's client name ("Acme Infra Ltd") as the scope rules use ("Acme
    Infra"): the scope whose words all appear in the name, longest first; else the name."""
    if not name:
        return None
    words = set(norm_name(name).split())
    with session_scope() as s:
        scopes = fstore.scope_values(s, "client")
    hits = [v for v in scopes if set(norm_name(v).split()) <= words]
    return max(hits, key=len) if hits else name


def _ready() -> None:
    with session_scope() as s:
        if active_ontology(s) is None:
            raise HTTPException(409, "No frozen schema yet: build the graph first.")


@router.post("/ask")
def ask(body: AskIn) -> dict[str, Any]:
    """Answer from the knowledge base only, with citations. `as_of` answers with the rules valid
    on that day; `known_at` with what the engine knew at that moment. An attached invoice sets
    the client when none is given and comes back on the card as `invoice_context`."""
    _ready()
    return _card(body)


def _card(body: AskIn) -> dict[str, Any]:
    ctx = plugin_context(invoice_id=body.invoice_id) if body.invoice_id else None
    if body.invoice_id and ctx is None:
        raise HTTPException(404, f"invoice {body.invoice_id} not found")
    client = body.client or _known_scope((ctx or {}).get("client"))
    card = answer(
        body.question,
        client=client,
        as_of=body.as_of,
        known_at=body.known_at,
        user_id=body.user_id,
        viewer=body.viewer,
    )
    if ctx is not None:
        card = {**card, "invoice_context": ctx}
    return card


# ---------------------------------------------------------------- asked without waiting

_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ask-job")
_JOBS: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()
_KEEP_S = 3600  # finished jobs are kept an hour, then dropped


def _run(job_id: str, body: AskIn) -> None:
    try:
        out: dict[str, Any] = {"status": "done", "card": _card(body)}
    except HTTPException as exc:
        out = {"status": "error", "status_code": exc.status_code, "error": str(exc.detail)}
    except Exception as exc:  # noqa: BLE001 - reported to the poller, never lost
        out = {"status": "error", "status_code": 500, "error": f"{type(exc).__name__}: {exc}"}
    with _LOCK:
        _JOBS[job_id].update(out, finished=time.time())


@router.post("/ask/jobs", status_code=202)
def ask_job(body: AskIn) -> dict[str, Any]:
    """Start answering; poll GET /ask/jobs/{job_id} for the card."""
    _ready()
    now = time.time()
    job_id = uuid.uuid4().hex
    with _LOCK:
        for k in [k for k, j in _JOBS.items() if now - j.get("finished", now) > _KEEP_S]:
            del _JOBS[k]
        _JOBS[job_id] = {"status": "pending", "started": now}
    _POOL.submit(copy_context().run, _run, job_id, body)
    return {"job_id": job_id, "status": "pending"}


@router.get("/ask/jobs/{job_id}")
def ask_job_status(job_id: str) -> dict[str, Any]:
    """`pending`, `done` (with `card`) or `error` (with `status_code` and `error`)."""
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            raise HTTPException(404, "unknown or expired job")
        out = {k: v for k, v in job.items() if k not in ("started", "finished")}
        out["seconds"] = round(job.get("finished", time.time()) - job["started"], 1)
    return {"job_id": job_id, **out}
