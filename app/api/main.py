"""FastAPI app (BUILD_PLAN Phase 7).

    uvicorn app.api.main:app --port 8000        # OpenAPI docs at /docs

The API is a thin layer: every endpoint calls the same store, answer and graph functions the
scripts and the worker use, so behaviour is identical whether work comes from the CLI, the web
app or another system. Long work (parsing, extraction, the conflict scan) is queued for the
worker; requests never wait on it.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import ask, changes, conflicts, episodes, insights, knowledge, plugins, review
from app.api.deps import TenantMiddleware
from app.core.config import get_settings

log = logging.getLogger("api")


def create_app() -> FastAPI:
    cfg = get_settings()
    app = FastAPI(
        title="Knowledge engine API",
        version="0.7.0",
        description=(
            "Ask questions with cited answers (also as of a past date), feed documents and "
            "messages in, inspect the bitemporal graph, review changes and conflicts. Every "
            "response carries the tenant's current kb_version in `X-KB-Version`; send "
            "`X-Tenant` to choose the tenant."
        ),
    )
    for r in (
        ask.router,
        episodes.router,
        knowledge.router,
        plugins.router,
        changes.router,
        review.router,
        conflicts.router,
        insights.router,
    ):
        app.include_router(r)

    @app.exception_handler(LookupError)
    async def lookup_error(_req: Request, exc: LookupError) -> JSONResponse:
        return JSONResponse({"detail": str(exc) or "not found"}, status_code=404)

    @app.exception_handler(Exception)
    async def unexpected(req: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error on %s %s", req.method, req.url.path)
        return JSONResponse(
            {"detail": "Internal error. It has been logged.", "error": type(exc).__name__},
            status_code=500,
        )

    # Outermost: CORS must also wrap error responses; the tenant is set before any handler.
    app.add_middleware(TenantMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in cfg.cors_origins.split(",") if o.strip()],
        allow_origin_regex=cfg.cors_origin_regex or None,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-KB-Version"],
    )
    return app


app = create_app()
