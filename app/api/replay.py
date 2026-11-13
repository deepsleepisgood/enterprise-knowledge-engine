"""Replay (Sources page): watch the knowledge base being rebuilt from empty, file by file.

GET /replay    the replay tenant's history, one step per file in arrival order, and the run state
POST /replay   start a fresh replay (empties the replay tenant; the main knowledge base is kept)

Each step's `done_at` is the instant to pass as `known_at` (with header `X-Tenant: <tenant>`) to
POST /ask or /ask/jobs, to ask what the engine knew right after that file.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import row
from app.core.config import get_settings
from app.core.db import session_scope
from app.ingest import replay
from app.store import history
from app.store.base import use_tenant

router = APIRouter(tags=["replay"])


class ReplayIn(BaseModel):
    by: str = Field(min_length=1, description="Who started it (shown on the page)")


@router.get("/replay")
def get_replay() -> dict[str, Any]:
    cfg = get_settings()
    run = replay.state()
    with use_tenant(cfg.replay_tenant), session_scope() as s:
        steps = history.steps(s, processing=bool(run.get("running")))
    return {
        "tenant": cfg.replay_tenant,
        "files": [p.name for p in replay.planned_files()],
        "run": run,
        "steps": [row(st) for st in steps],
    }


@router.post("/replay", status_code=202)
def start_replay(body: ReplayIn) -> dict[str, Any]:
    if not get_settings().llm_configured:
        raise HTTPException(503, "No language model is configured, so documents cannot be read.")
    try:
        return replay.start(body.by)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(409, str(exc)) from exc
