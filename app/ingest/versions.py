"""New versions of a known document (BUILD_PLAN Phase 1).

A new source matches an existing one when both have the same document type and the same
reference code, or very similar titles. The newer one (higher version, else later date) gets
`supersedes_source_id`; the older one becomes `superseded` from the day the newer takes effect.
This works in either arrival order. Passages with identical text are marked as carried over so
extraction can reuse their facts; passages that disappeared become a review item.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy.orm import Session

from app.store import episodes as store
from app.store import kb

TITLE_SIMILARITY = 0.85


def version_key(v: str | None) -> tuple[int, ...]:
    if not v:
        return ()
    return tuple(int(x) for x in re.findall(r"\d+", v))


def _norm_title(t: str | None) -> str:
    t = re.sub(r"\b(v(ersion)?\s*\d+(\.\d+)*|\d{4})\b", " ", (t or "").lower())
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def same_document(a: Any, b: Any) -> bool:
    if a.id == b.id or a.episode_id == b.episode_id or a.doc_type != b.doc_type:
        return False
    ra, rb = (a.meta or {}).get("ref"), (b.meta or {}).get("ref")
    if ra and rb:
        return ra == rb
    ta, tb = _norm_title(a.title), _norm_title(b.title)
    return bool(ta) and SequenceMatcher(None, ta, tb).ratio() >= TITLE_SIMILARITY


def newer(a: Any, b: Any) -> bool:
    va, vb = version_key(a.version), version_key(b.version)
    if va and vb and va != vb:
        return va > vb
    if a.dated and b.dated and a.dated != b.dated:
        return a.dated > b.dated
    return False


@dataclass
class VersionLink:
    newer_id: str
    older_id: str
    carried: int
    added: int
    removed: int


def _supersede(session: Session, new: Any, old: Any) -> None:
    until = new.dated - timedelta(days=1) if new.dated else None
    note = f"superseded by {new.short_label}" + (f" from {new.dated:%d %b %Y}" if new.dated else "")
    values: dict[str, Any] = {"status": "superseded", "status_note": note}
    if until and (old.valid_until is None or old.valid_until > until):
        values["valid_until"] = until
    store.update_source(session, old.id, **values)
    store.update_source(session, new.id, supersedes_source_id=old.id)


def link_versions(session: Session, source_id: str) -> list[VersionLink]:
    src = store.get_source(session, source_id)
    links: list[VersionLink] = []
    for other in store.list_sources(session):
        if not same_document(src, other):
            continue
        new, old = (src, other) if newer(src, other) else (other, src)
        if new is old or not newer(new, old):
            continue
        _supersede(session, new, old)
        old_p = {p.content_hash: p for p in store.passages_for_source(session, old.id)}
        new_p = store.passages_for_source(session, new.id)
        carried = 0
        for p in new_p:
            prev = old_p.get(p.content_hash)
            if prev is not None:
                carried += 1
                store.update_passage(
                    session, p.id, meta={**(p.meta or {}), "carried_from": prev.id}
                )
        new_hashes = {p.content_hash for p in new_p}
        removed = [
            p
            for p in old_p.values()
            if p.content_hash not in new_hashes and (p.meta or {}).get("leaf")
        ]
        if removed and new is src:
            kb.add_review_item(
                session,
                "retire",
                {
                    "summary": f"{len(removed)} passages of {old.short_label} are not in "
                    f"{new.short_label}; retire their facts?",
                    "source_id": old.id,
                    "superseded_by": new.id,
                    "passage_ids": [p.id for p in removed],
                },
            )
        links.append(VersionLink(new.id, old.id, carried, len(new_p) - carried, len(removed)))
    return links
