"""Intake: submit episodes (text, e-mail, files, folders, zips) and follow them through the
pipeline. Parsing and extraction run as jobs on the worker; these endpoints only register."""

from __future__ import annotations

import base64
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.api.deps import not_found, read_session, row, write_session
from app.core.config import get_settings
from app.ingest.connectors import EpisodeIn, from_eml, from_text, from_upload
from app.ingest.intake import submit
from app.store import episodes as estore
from app.store import facts as fstore
from app.store import jobs

router = APIRouter(tags=["episodes"])


class EpisodeTextIn(BaseModel):
    """Raw text (a chat message, a note) or a whole RFC 822 e-mail (base64 in `eml_base64`)."""

    text: str | None = Field(default=None, max_length=200_000)
    eml_base64: str | None = None
    subject: str | None = None
    sender: str | None = None
    sender_role: str | None = None
    channel: str = "api"
    effective_hint: date | None = None
    scope_hint: str | None = None

    @model_validator(mode="after")
    def one_body(self) -> EpisodeTextIn:
        if bool(self.text) == bool(self.eml_base64):
            raise ValueError("give exactly one of text or eml_base64")
        return self


def _submit_all(s: Session, eps: list[EpisodeIn]) -> list[dict[str, Any]]:
    out = []
    for ep in eps:
        eid, created = submit(s, ep)
        out.append({"episode_id": eid, "file": ep.filename, "created": created})
    return out


@router.post("/episodes", status_code=202)
def post_episode(body: EpisodeTextIn, s: Session = Depends(write_session)) -> dict[str, Any]:
    hints = {
        "sender_role": body.sender_role,
        "effective_hint": body.effective_hint,
        "scope_hint": body.scope_hint,
    }
    if body.eml_base64:
        try:
            raw = base64.b64decode(body.eml_base64, validate=True)
        except ValueError as exc:
            raise HTTPException(422, "eml_base64 is not valid base64") from exc
        eps = from_eml(raw, **hints)
    else:
        eps = [
            from_text(
                body.text or "",
                channel=body.channel,
                sender=body.sender,
                subject=body.subject,
                **hints,
            )
        ]
    return {"episodes": _submit_all(s, eps)}


@router.get("/connectors")
def connectors() -> dict[str, Any]:
    """Connector status for the Sources page (the watched folder's path and last scan)."""
    from app.ingest import watch

    return {"watched_folder": watch.status()}


@router.post("/episodes/upload", status_code=202)
async def upload(
    files: list[UploadFile] = File(...),
    sender: str | None = None,
    sender_role: str | None = None,
    s: Session = Depends(write_session),
) -> dict[str, Any]:
    """One or more files; a folder is sent as its files, a zip expands to its members.
    `sender_role` lets governance match the sender-authority map (app/govern)."""
    limit = get_settings().max_upload_mb * 1024 * 1024
    eps: list[EpisodeIn] = []
    for f in files:
        data = await f.read(limit + 1)
        if len(data) > limit:
            raise HTTPException(413, f"{f.filename} is larger than {limit // 2**20} MB")
        eps += from_upload(f.filename or "upload.bin", data, sender=sender, sender_role=sender_role)
    if not eps:
        raise HTTPException(422, "no usable files (empty, hidden or system files are skipped)")
    return {"episodes": _submit_all(s, eps)}


METADATA_FIELDS = ("doc_type", "dated", "status", "version", "scope")
LOW_CONFIDENCE = 0.6


def source_brief(src: Any) -> dict[str, Any]:
    """A document with the metadata the engine was unsure of (for the owner to correct)."""
    prov = src.meta_provenance or {}
    unsure = [
        {
            "field": f,
            "origin": (prov.get(f) or {}).get("origin", ""),
            "confidence": (prov.get(f) or {}).get("confidence"),
        }
        for f in METADATA_FIELDS
        if (prov.get(f) or {}).get("confidence") is not None
        and prov[f]["confidence"] < LOW_CONFIDENCE
        and not src.confirmed_by
    ]
    return {
        "id": src.id,
        "short_label": src.short_label,
        "title": src.title,
        "doc_type": src.doc_type,
        "version": src.version,
        "dated": src.dated,
        "status": src.status,
        "client_scope": src.client_scope,
        "confirmed_by": src.confirmed_by,
        "unsure": unsure,
    }


@router.get("/episodes")
def list_episodes(limit: int = 200, s: Session = Depends(read_session)) -> list[dict[str, Any]]:
    """Newest first, with each episode's documents, passage and fact counts."""
    eps = estore.list_episodes(s, limit=min(max(limit, 1), 1000))
    passages, facts = estore.passage_counts(s), fstore.counts_by_episode(s)
    docs: dict[str, list[dict[str, Any]]] = {}
    for src in estore.list_sources(s):
        docs.setdefault(src.episode_id, []).append(source_brief(src))
    return [
        {
            **row(e, drop={"blob_path"}),
            "passages": passages.get(e.id, 0),
            "facts": facts.get(e.id, 0),
            "sources": docs.get(e.id, []),
        }
        for e in eps
    ]


@router.post("/episodes/{episode_id}/retry", status_code=202)
def retry(episode_id: str, s: Session = Depends(write_session)) -> dict[str, Any]:
    """Parse a failed or held episode again (the failed attempt stays in the job log)."""
    e = estore.get_episode(s, episode_id)
    if e is None:
        raise not_found("episode")
    if e.status not in ("failed", "needs_attention"):
        raise HTTPException(409, f"episode is {e.status}; only failed or held episodes retry")
    estore.set_status(s, episode_id, "queued", error=None)
    job = jobs.retry(s, "parse_episode", {"episode_id": episode_id})
    return {"episode_id": episode_id, "status": "queued", "job_id": job}


class SourceEdit(BaseModel):
    by: str
    doc_type: str | None = None
    version: str | None = None
    dated: date | None = None
    status: str | None = None
    client_scope: str | None = None


@router.patch("/sources/{source_id}")
def edit_source(source_id: str, body: SourceEdit, s: Session = Depends(write_session)) -> dict:
    """The owner corrects inferred metadata once; the document's facts are re-resolved (a new
    date or status can change which rule is in force)."""
    src = estore.get_source(s, source_id)
    if src is None:
        raise not_found("document")
    values = body.model_dump(exclude_none=True, exclude={"by"})
    prov = dict(src.meta_provenance or {})
    for f in values:
        key = "scope" if f == "client_scope" else f
        prov[key] = {"origin": f"confirmed by {body.by}", "confidence": 1.0}
    estore.update_source(s, source_id, **values, meta_provenance=prov, confirmed_by=body.by)
    job = jobs.enqueue(s, "reresolve_source", {"source_id": source_id})
    return {"source_id": source_id, "updated": sorted(values), "reresolve_job": job}


@router.get("/episodes/{episode_id}")
def get_episode(episode_id: str, s: Session = Depends(read_session)) -> dict[str, Any]:
    """Pipeline status, parse tier and quality, errors, its documents and the facts it produced."""
    e = estore.get_episode(s, episode_id)
    if e is None:
        raise not_found("episode")
    facts = fstore.live_for_episode(s, episode_id)
    by_status: dict[str, int] = {}
    for f in facts:
        by_status[f.status] = by_status.get(f.status, 0) + 1
    return {
        **row(e, drop={"blob_path"}),
        "has_original": bool(e.blob_path and Path(e.blob_path).exists()),
        "sources": [row(src) for src in estore.list_sources(s, episode_id=episode_id)],
        "passages": len(estore.passages_for_episode(s, episode_id)),
        "facts": {"total": len(facts), "by_status": by_status},
    }


@router.get("/episodes/{episode_id}/original")
def original(episode_id: str, s: Session = Depends(read_session)) -> FileResponse:
    e = estore.get_episode(s, episode_id)
    if e is None or not e.blob_path or not Path(e.blob_path).exists():
        raise not_found("original file")
    name = Path(e.source_uri or "original").name
    return FileResponse(e.blob_path, media_type=e.mime or None, filename=name)
