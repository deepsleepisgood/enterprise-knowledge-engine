"""Change feed items: what changed, from what to what, from when, how many have seen it, and
whether the document still in force needs editing (shared by `/changes` and the digest)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.graph.conflicts import value_text
from app.store import episodes as estore
from app.store import facts as fstore
from app.store import kb

PROVISIONAL = {"pending", "provisional"}


def as_written(f: Any) -> str:
    """A fact's value in the source's own words ("2%", "10 thousand"), else the normalised form."""
    v = f.value or {}
    if v.get("text") and not v.get("items"):
        return str(v["text"])
    return value_text(f)


def needs_document_edit(new: Any, old: Any, old_source: Any) -> bool:
    """A confirmed rule replaced one that a document still in force states: that document now
    says something the knowledge base no longer holds, so the owner should edit it."""
    return (
        new is not None
        and old is not None
        and new.retracted_at is None
        and new.status not in PROVISIONAL
        and old.passage_id is not None
        and old.source_id != new.source_id
        and old_source is not None
        and old_source.status == "current"
    )


def change_items(
    session: Session, rows: list[Any], user_id: str | None = None
) -> list[dict[str, Any]]:
    """Feed items; with `user_id`, each also says whether that user has acknowledged it."""
    fact_ids = sorted({i for c in rows for i in (c.new_fact, c.old_fact) if i})
    facts = fstore.by_ids(session, fact_ids)
    acks = kb.ack_counts(session, [c.id for c in rows])
    mine = kb.acked_by(session, user_id, [c.id for c in rows]) if user_id else set()
    sources: dict[str, Any] = {}
    out = []
    for c in rows:
        new, old = facts.get(c.new_fact or -1), facts.get(c.old_fact or -1)
        ref = new or old
        if new is None:  # a fact withdrawn (a rejected provisional one) or retired
            status = (
                "confirmed"
                if old is None
                else ("rejected" if old.status in PROVISIONAL else "retired")
            )
        elif new.retracted_at is not None:
            status = "rejected"
        else:
            status = "provisional" if new.status in PROVISIONAL else "confirmed"
        old_src = None
        if old is not None and old.source_id:
            if old.source_id not in sources:
                sources[old.source_id] = estore.get_source(session, old.source_id)
            old_src = sources[old.source_id]
        edit = needs_document_edit(new, old, old_src)
        out.append(
            {
                "id": c.id,
                "kb_version": c.kb_version,
                "summary": c.summary,
                "topic": (ref.subject_name or ref.attribute) if ref else "",
                "attribute": ref.attribute if ref else None,
                "old_value": as_written(old) if old else "",
                "new_value": as_written(new) if new else "",
                "effective_at": c.effective_at or c.created_at,
                "created_at": c.created_at,
                "status": status,
                "source_label": (new.source_label if new else None) or "",
                "acknowledged": acks.get(c.id, 0),
                "seen": c.id in mine,
                "document_edit": (
                    {"document": old_src.short_label, "locator": old.locator or ""}
                    if edit and old_src is not None and old is not None
                    else None
                ),
            }
        )
    return out
