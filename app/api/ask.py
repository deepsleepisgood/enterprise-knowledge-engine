"""POST /ask: a question in, an answer card out."""

from __future__ import annotations

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


@router.post("/ask")
def ask(body: AskIn) -> dict[str, Any]:
    """Answer from the knowledge base only, with citations. `as_of` answers with the rules valid
    on that day; `known_at` with what the engine knew at that moment. An attached invoice sets
    the client when none is given and comes back on the card as `invoice_context`."""
    with session_scope() as s:
        if active_ontology(s) is None:
            raise HTTPException(409, "No frozen schema yet: build the graph first.")
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
