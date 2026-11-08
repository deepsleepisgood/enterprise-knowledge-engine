"""The graph as callers see it: schema, entities and their timelines, facts, passages."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import not_found, parse_day, parse_instant, read_session, row, write_session
from app.graph.ontology import Ontology
from app.store import entities as ents
from app.store import episodes as estore
from app.store import facts as fstore
from app.store import kb

router = APIRouter(tags=["knowledge"])


# ---------------------------------------------------------------- schema


def _schema(sc: Any) -> dict[str, Any] | None:
    return row(sc) if sc is not None else None


@router.get("/schema")
def get_schema(s: Session = Depends(read_session)) -> dict[str, Any]:
    """The frozen schema answers run on, and the latest draft (if newer) awaiting review."""
    active, latest = kb.active_schema(s), kb.latest_schema(s)
    if active is not None and active.status != "frozen":
        active = None  # only a draft exists
    draft = latest if latest is not None and latest.status == "draft" else None
    return {
        "active": _schema(active),
        "draft": _schema(draft),
        "kb_version": kb.current_kb_version(s),
    }


class SchemaEdit(BaseModel):
    version: int
    ontology: dict[str, Any]


@router.put("/schema")
def put_schema(body: SchemaEdit, s: Session = Depends(write_session)) -> dict[str, Any]:
    """Edit a draft. Frozen versions are immutable: edit the next draft instead."""
    sc = kb.get_schema(s, body.version)
    if sc is None:
        raise not_found(f"schema v{body.version}")
    if sc.status != "draft":
        raise HTTPException(409, f"schema v{body.version} is {sc.status}; only drafts can change")
    try:
        Ontology.model_validate(body.ontology)
    except ValueError as exc:
        raise HTTPException(422, f"not a valid schema: {exc}") from exc
    kb.update_schema(s, body.version, body.ontology)
    return {"version": body.version, "status": "draft"}


class Freeze(BaseModel):
    version: int
    by: str


@router.post("/schema/freeze")
def freeze(body: Freeze) -> dict[str, Any]:
    """Approve a draft: freeze it and re-key the facts its review item maps (one publish)."""
    from app.graph.pipeline import apply_schema

    try:
        return apply_schema(body.version, body.by)
    except LookupError as exc:
        raise not_found(f"schema v{body.version}") from exc


# ---------------------------------------------------------------- entities


@router.get("/entities")
def list_entities(type: str | None = None, s: Session = Depends(read_session)) -> list[dict]:
    return [row(e, drop={"score"}) for e in ents.list_entities(s, type_=type)]


@router.get("/entities/{entity_id}")
def get_entity(entity_id: str, s: Session = Depends(read_session)) -> dict[str, Any]:
    e = ents.get(s, entity_id)
    if e is None:
        raise not_found("entity")
    facts = fstore.get_facts(s, subject_id=entity_id)
    return {**row(e, drop={"score"}), "facts": [row(f) for f in facts]}


@router.get("/entities/{entity_id}/timeline")
def timeline(
    entity_id: str, attribute: str | None = None, s: Session = Depends(read_session)
) -> dict[str, Any]:
    """Every version of every fact about the entity, retired ones included, grouped by
    attribute: when each was true (valid time) and when the engine knew it (transaction time)."""
    e = ents.get(s, entity_id)
    if e is None:
        raise not_found("entity")
    by_attr: dict[str, list[dict[str, Any]]] = {}
    for f in fstore.timeline(s, entity_id, attribute):
        by_attr.setdefault(f.attribute, []).append(row(f))
    return {
        "entity": row(e, drop={"score"}),
        "attributes": [{"attribute": a, "versions": v} for a, v in by_attr.items()],
    }


class Merge(BaseModel):
    keep_id: str
    drop_id: str
    by: str


@router.post("/entities/merge")
def merge(body: Merge, s: Session = Depends(write_session)) -> dict[str, Any]:
    """Owner correction: two entities are one. Facts stay where they are and read through the
    merge; nothing is deleted, so the merge can be audited."""
    if body.keep_id == body.drop_id:
        raise HTTPException(422, "keep_id and drop_id are the same entity")
    if ents.get(s, body.keep_id) is None or ents.get(s, body.drop_id) is None:
        raise not_found("entity")
    ents.merge(s, body.keep_id, body.drop_id)
    return {"kept": body.keep_id, "merged": body.drop_id, "by": body.by}


@router.post("/entities/{entity_id}/split", status_code=501)
def split(entity_id: str) -> dict[str, Any]:
    """Cut line (BUILD_PLAN Phase 7): splitting needs per-mention provenance on facts."""
    raise HTTPException(501, "Splitting an entity is not available in the MVP (cut line).")


# ---------------------------------------------------------------- facts and passages


@router.get("/facts")
def facts(
    entity: str | None = None,
    attribute: str | None = None,
    client: str | None = None,
    valid_on: str | None = None,
    known_at: str | None = None,
    status: str | None = None,
    kind: str | None = None,
    limit: int = 500,
    s: Session = Depends(read_session),
) -> list[dict[str, Any]]:
    """Facts by entity, attribute and client scope, as of a valid day (`valid_on`) and a
    transaction time (`known_at`: what the engine believed then)."""
    rows = fstore.get_facts(
        s,
        subject_id=entity,
        attribute=attribute,
        scope={"client": client} if client else None,
        valid_on=parse_day(valid_on, "valid_on"),
        known_at=parse_instant(known_at, "known_at"),
        statuses=[x for x in (status or "").split(",") if x] or None,
        kinds=[x for x in (kind or "").split(",") if x] or None,
    )
    return [row(f) for f in rows[: min(max(limit, 1), 5000)]]


@router.get("/passages/{passage_id}")
def passage(passage_id: str, s: Session = Depends(read_session)) -> dict[str, Any]:
    """A passage with its document's version, date and status, and where it sits in the
    original (ordinal, parent and neighbours), for the source drawer."""
    p = estore.get_passage(s, passage_id)
    if p is None:
        raise not_found("passage")
    src = estore.get_source(s, p.source_id)
    siblings = estore.passages_for_source(s, p.source_id, live=False)
    idx = next((i for i, x in enumerate(siblings) if x.id == p.id), None)

    def brief(x: Any) -> dict[str, Any] | None:
        return {"id": x.id, "locator": x.locator, "section_title": x.section_title} if x else None

    return {
        **row(p),
        "source": row(src, drop={"meta_provenance"}) if src else None,
        "episode_id": p.episode_id,
        "position_in_source": {
            "index": idx,
            "of": len(siblings),
            "previous": brief(siblings[idx - 1]) if idx else None,
            "next": brief(siblings[idx + 1])
            if idx is not None and idx + 1 < len(siblings)
            else None,
        },
        "facts": [row(f) for f in fstore.live_for_passages(s, [p.id])],
    }
