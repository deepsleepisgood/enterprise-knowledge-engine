"""Graph jobs: schema management, extraction and publishing per episode.

    ensure_schema()          induced (or the plug-in baseline when SCHEMA_MODE=baseline)
    extract_episode job      leaf passages -> drafts (parallel LLM calls) -> one publish
Passages carried over unchanged from an earlier version reuse its facts instead of an LLM call.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Any

from app.core.config import get_settings
from app.core.db import session_scope
from app.graph import induce
from app.graph.compare import LLMComparator, deterministic
from app.graph.entities import Resolver
from app.graph.extract import Draft, extract_passage
from app.graph.ontology import Ontology
from app.graph.write import PublishReport, publish
from app.store import episodes as estore
from app.store import facts as fstore
from app.store import kb
from app.worker import handler

log = logging.getLogger("graph")
EXTRACT_WORKERS = 6


class SchemaNotReady(RuntimeError):
    pass


def active_ontology(session: Any, mode: str | None = None) -> Ontology | None:
    mode = mode or get_settings().schema_mode
    row = kb.active_schema(session, mode=mode)
    if row is None or row.status != "frozen":
        return None
    return Ontology.model_validate(row.ontology)


def ensure_schema(
    auto_freeze: bool = False, mode: str | None = None, structured_fn=None
) -> tuple[int, str]:
    """Make sure a schema exists. Returns (version, status)."""
    mode = mode or get_settings().schema_mode
    with session_scope() as s:
        row = kb.active_schema(s, mode=mode)
        if row is not None:
            if auto_freeze and row.status != "frozen":
                kb.freeze_schema(s, row.version, "auto")
                return row.version, "frozen"
            return row.version, row.status
        if mode == "baseline":
            from app.plugins import registry

            data = registry.baseline_schema()
            if not data:
                raise SchemaNotReady("SCHEMA_MODE=baseline but no plug-in provides a schema")
            onto = Ontology.model_validate(data)
            v = kb.save_schema(s, onto.model_dump(), "baseline", frozen_by="baseline")
            return v, "frozen"
        passages = estore.extractable_passages(s)
        sources = estore.list_sources(s)
        snap_p = [_Snap(p) for p in passages]
        snap_s = [_Snap(x) for x in sources]
    onto, sample_ids = induce.induce(snap_p, snap_s, structured_fn=structured_fn)
    with session_scope() as s:
        v = kb.save_schema(
            s,
            onto.model_dump(),
            "induced",
            sample=sample_ids,
            frozen_by="auto" if auto_freeze else None,
        )
        if not auto_freeze:
            kb.add_review_item(
                s, "schema", {"version": v, "summary": "Induced schema ready to review"}
            )
    return v, "frozen" if auto_freeze else "draft"


class _Snap:
    """Detached copy of an ORM row's plain attributes (safe across threads and sessions)."""

    def __init__(self, row: Any) -> None:
        for col in row.__table__.columns:
            setattr(self, col.key, getattr(row, col.key))


def _carried_drafts(session: Any, p: _Snap, src: _Snap) -> list[Draft] | None:
    old_id = (p.meta or {}).get("carried_from")
    if not old_id:
        return None
    rows = fstore.live_for_passages(session, [old_id])
    if not rows:
        return None
    out = []
    for i, r in enumerate(rows):
        m = r.meta or {}
        out.append(
            Draft(
                origin_key=f"{p.id}:carried:{i}:{r.origin_key.rsplit(':', 1)[-1]}",
                attribute=r.attribute,
                topic=m.get("topic", "other"),
                about=None,
                about_type=None,
                value=r.value,
                client=(r.scope or {}).get("client"),
                scope={k: v for k, v in (r.scope or {}).items() if k != "client_id"},
                condition=r.condition,
                kind=r.kind,
                statement=r.statement,
                quote=r.quote or "",
                quote_verified=bool(m.get("quote_verified")),
                asserted_from=src.dated,
                asserted_to=src.valid_until,
                passage_id=p.id,
                source_id=src.id,
                episode_id=p.episode_id,
                meta={"carried_from_fact": r.id},
            )
        )
    return out


def extract_and_publish(
    episode_id: str | None = None,
    structured_fn=None,
    compare=None,
    embed_fn: Any = "default",
    workers: int = EXTRACT_WORKERS,
    limit: int | None = None,
) -> dict[str, Any]:
    with session_scope() as s:
        onto = active_ontology(s)
        if onto is None:
            raise SchemaNotReady("no frozen schema: run scripts/build_graph.py or freeze in Setup")
        passages = [_Snap(p) for p in estore.extractable_passages(s, episode_id)][:limit]
        sources = {
            k: _Snap(v)
            for k, v in estore.sources_by_ids(s, sorted({p.source_id for p in passages})).items()
        }
        episodes = {p.episode_id for p in passages}
        msg_dates: dict[str, date] = {}
        for eid in episodes:
            ep = estore.get_episode(s, eid)
            if ep is not None and ep.channel in ("email", "api", "expert_answer"):
                msg_dates[eid] = ep.received_at.date()
        carried: dict[str, list[Draft]] = {}
        for p in passages:
            c = _carried_drafts(s, p, sources[p.source_id])
            if c is not None:
                carried[p.id] = c

    failures: list[str] = []

    def run(p: _Snap) -> list[Draft]:
        if p.id in carried:
            return carried[p.id]
        try:
            return extract_passage(
                p,
                sources[p.source_id],
                onto,
                msg_dates.get(p.episode_id),
                structured_fn=structured_fn,
            )
        except Exception as exc:  # one bad passage must not sink the episode
            failures.append(
                f"{p.id} ({sources[p.source_id].short_label} {p.locator}): "
                f"{type(exc).__name__}: {str(exc)[:200]}"
            )
            return []

    with ThreadPoolExecutor(max_workers=workers) as pool:
        per_passage = list(pool.map(run, passages))
    drafts = [d for ds in per_passage for d in ds]
    done_ids = [
        p.id
        for p, ds in zip(passages, per_passage, strict=True)
        if not any(p.id in f for f in failures)
    ]

    if compare is None:
        compare = (
            LLMComparator(structured_fn)
            if get_settings().llm_configured or structured_fn
            else deterministic
        )
    if embed_fn == "default":
        from app.core.embed import embed as embed_fn
    with session_scope() as s:
        resolver = Resolver(
            s,
            structured_fn=structured_fn if structured_fn else _default_structured(),
            embed_fn=embed_fn,
        )
        rep: PublishReport = publish(
            s,
            drafts,
            done_ids,
            onto,
            compare,
            resolver,
            summary=f"extraction of {episode_id or 'all episodes'}",
            episode_id=episode_id,
        )
        for eid in episodes if episode_id is None else [episode_id]:
            estore.set_status(s, eid, "published")
    return {
        "passages": len(passages),
        "carried": len(carried),
        "drafts": len(drafts),
        "failures": failures,
        "inserted": rep.inserted,
        "revised": rep.revised,
        "retired": rep.retired,
        "unchanged": rep.unchanged,
        "conflicts": rep.conflicts,
        "statuses": dict(rep.statuses),
        "kb_version": rep.kb_version,
        "compare_failures": getattr(compare, "failures", []),
        "entity_decisions": rep.entity_decisions,
    }


def _default_structured():
    if not get_settings().llm_configured:
        return None
    from app.core.llm import structured

    return structured


def reresolve_source(source_id: str, compare=None) -> dict[str, Any]:
    """Re-run resolution for every group a source has facts in (after its status changed)."""
    with session_scope() as s:
        onto = active_ontology(s)
        if onto is None:
            return {"skipped": "no frozen schema"}
        rows = fstore.get_facts(s)
        groups = {(r.subject_id, r.attribute) for r in rows if r.source_id == source_id}
        if not groups:
            return {"groups": 0}
        resolver = Resolver(s, structured_fn=_default_structured())
        rep = publish(
            s,
            [],
            [],
            onto,
            compare or LLMComparator(_default_structured())
            if get_settings().llm_configured
            else compare or deterministic,
            resolver,
            summary=f"re-resolution after {source_id} changed status",
            extra_groups=groups,
        )
    return {"groups": len(groups), "revised": rep.revised, "kb_version": rep.kb_version}


@handler("reresolve_source")
def reresolve_source_job(payload: dict[str, Any]) -> dict[str, Any]:
    return reresolve_source(payload["source_id"])


@handler("extract_episode")
def extract_episode(payload: dict[str, Any]) -> dict[str, Any]:
    with session_scope() as s:
        if active_ontology(s) is None:
            return {"skipped": "no frozen schema yet; build_graph will re-queue"}
    out = extract_and_publish(payload["episode_id"])
    out.pop("entity_decisions", None)
    return out
