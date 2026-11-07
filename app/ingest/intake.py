"""Intake: keep the original, dedupe by content hash, detect the type, queue parsing."""

from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.ingest.connectors import EpisodeIn
from app.ingest.detect import detect
from app.store import episodes as store
from app.store import jobs
from app.store.base import tenant


def store_blob(data: bytes, digest: str, filename: str) -> Path:
    suffix = Path(filename).suffix.lower()[:10]
    d = get_settings().blob_dir / tenant() / digest[:2]
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{digest}{suffix}"
    if not path.exists():
        path.write_bytes(data)
    return path


def submit(session: Session, ep: EpisodeIn, enqueue: bool = True) -> tuple[str, bool]:
    """Register one episode. Returns (episode_id, created); duplicates only add a confirmation."""
    digest = hashlib.sha256(ep.data).hexdigest()
    kind, mime = detect(ep.data, ep.filename)
    path = store_blob(ep.data, digest, ep.filename)
    eid, created = store.add_episode(
        session,
        channel=ep.channel,
        content_hash=digest,
        received_at=ep.received_at,
        source_uri=ep.filename,
        blob_path=str(path),
        mime=mime,
        sender=ep.sender,
        sender_role=ep.sender_role,
        effective_hint=ep.effective_hint,
        scope_hint=ep.scope_hint,
        meta={"kind": kind, "bytes": len(ep.data), **ep.meta},
    )
    if created and enqueue:
        jobs.enqueue(session, "parse_episode", {"episode_id": eid})
    return eid, created
