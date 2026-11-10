"""Splitting an entity the engine merged by mistake (owner correction, SCOPE 4.2).

The owner names the aliases that are really a different entity. A live fact moves with them
when its own words (statement, condition, quote) name one of those aliases: as its subject, as
its object, or as its client scope. Each moved fact is a new version (the old row is retracted,
never deleted), and the groups on both sides are resolved again.
"""

from __future__ import annotations

from typing import Any

from app.core.db import session_scope
from app.store import entities as ents
from app.store import facts as fstore
from app.store.base import norm_name


def _mentions(text: str, names: list[str]) -> bool:
    t = f" {norm_name(text)} "
    return any(f" {norm_name(n)} " in t for n in names if norm_name(n))


def split_entity(entity_id: str, new_name: str, aliases: list[str], by: str) -> dict[str, Any]:
    from app.graph.compare import LLMComparator, deterministic
    from app.graph.entities import Resolver
    from app.graph.pipeline import _default_structured, active_ontology
    from app.graph.write import publish

    names = [a for a in {*aliases, new_name} if a.strip()]
    with session_scope() as s:
        old = ents.get(s, entity_id)
        if old is None:
            raise LookupError(entity_id)
        new_id = ents.split(s, entity_id, new_name, aliases)
        moved, groups = 0, set()
        for f in fstore.get_facts(s):
            sc = dict(f.scope or {})
            on_subject = f.subject_id == entity_id
            on_object = f.object_id == entity_id
            on_client = sc.get("client_id") == entity_id or sc.get("client") == old.name
            if not (on_subject or on_object or on_client):
                continue
            text = " ".join(x for x in (f.statement, f.condition, f.quote) if x)
            if not _mentions(text, names):
                continue
            changes: dict[str, Any] = {}
            if on_subject:
                changes["subject_id"] = new_id
            if on_object:
                changes["object_id"] = new_id
            if on_client:
                sc["client"], sc["client_id"] = new_name, new_id
                changes["scope"] = sc
            fstore.revise(s, f.id, **changes)
            groups |= {
                (f.subject_id, f.attribute),
                (changes.get("subject_id", f.subject_id), f.attribute),
            }
            moved += 1
        onto = active_ontology(s)
        kbv = None
        if onto is not None and groups:
            structured = _default_structured()
            rep = publish(
                s,
                [],
                [],
                onto,
                LLMComparator(structured) if structured else deterministic,
                Resolver(s, structured_fn=structured),
                summary=f"{new_name} split from {old.name} by {by}: {moved} facts moved",
                extra_groups=groups,
            )
            kbv = rep.kb_version
    return {"entity_id": new_id, "split_from": entity_id, "moved_facts": moved, "kb_version": kbv}
