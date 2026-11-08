"""Shared API plumbing: tenant and kb_version middleware, sessions, serialisers, errors.

Every request runs for one tenant (header `X-Tenant`, else TENANT_ID). Reads use one snapshot
transaction, so a response never mixes two kb versions. Every response carries the tenant's
current `kb_version` in the `X-KB-Version` header; object bodies also carry it as `kb_version`
(list bodies stay plain lists, which is what the web client reads).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from datetime import date, datetime
from typing import Any

import anyio
from fastapi import HTTPException
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.db import session_scope, snapshot_scope
from app.store import kb
from app.store.base import tenant, use_tenant

TENANT_HEADER = b"x-tenant"
KB_HEADER = b"x-kb-version"
_SKIP_COLUMNS = {"embedding", "tsv", "tenant_id"}


def kb_version_now(tenant_id: str) -> int:
    with use_tenant(tenant_id), session_scope() as s:
        return kb.current_kb_version(s)


class TenantMiddleware:
    """Sets the tenant for the whole request and stamps `X-KB-Version` on the response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        raw = headers.get(TENANT_HEADER, b"").decode("latin-1").strip()
        tenant_id = raw or tenant()

        async def send_with_version(message: Message) -> None:
            if message["type"] == "http.response.start" and scope.get("path") != "/health":
                try:
                    v = await anyio.to_thread.run_sync(kb_version_now, tenant_id)
                    message.setdefault("headers", [])
                    message["headers"].append((KB_HEADER, str(v).encode()))
                except Exception:  # the header is informative; never fail a response for it
                    pass
            await send(message)

        with use_tenant(tenant_id):
            await self.app(scope, receive, send_with_version)


def read_session() -> Iterator[Session]:
    with snapshot_scope() as s:
        yield s


def write_session() -> Iterator[Session]:
    with session_scope() as s:
        yield s


def row(obj: Any, drop: set[str] | None = None) -> dict[str, Any]:
    """An ORM row or a dataclass as a plain dict (no embeddings, tsvector or tenant id)."""
    skip = _SKIP_COLUMNS | (drop or set())
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {k: v for k, v in dataclasses.asdict(obj).items() if k not in skip}
    return {
        a.key: getattr(obj, a.key) for a in sa_inspect(obj).mapper.column_attrs if a.key not in skip
    }


def not_found(what: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"{what} not found")


def parse_day(value: str | None, name: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError as exc:
        raise HTTPException(422, f"{name} must be a date (YYYY-MM-DD)") from exc


def parse_instant(value: str | None, name: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(422, f"{name} must be an ISO date or date-time") from exc
