"""The write path (BUILD_PLAN Phase 2d and CLAUDE.md rule 7): publish extracted facts.

In one transaction:
1. Resolve subjects, clients and mentions to entities.
2. Retire live facts of these passages that the new extraction no longer states.
3. For each (subject, attribute) group touched, fetch only that group's live facts, re-run
   authority resolution over their assertions plus the new ones, and write the outcome:
   unchanged rows stay, changed rows are revised (retract + new version), new facts inserted.
4. Record conflicts, bump kb_version and write change rows when anything changed.
Resolution reads each assertion's own interval (meta.asserted_from/to) and its source's current
status and rank, so the result does not depend on the order episodes arrive.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.graph.entities import Resolver, norm_type
from app.graph.extract import Draft
from app.graph.ontology import Ontology
from app.graph.resolve import Assertion, Comparator, resolve_group
from app.graph.scope import distinctive_words, fact_client, infers_scope
from app.store import episodes as estore
from app.store import facts as fstore
from app.store import kb
from app.store.base import advisory_lock, day_start, tenant, utcnow


@dataclass
class PublishReport:
    inserted: int = 0
    revised: int = 0
    retired: int = 0
    unchanged: int = 0
    conflicts: int = 0
    kb_version: int | None = None
    statuses: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    entity_decisions: list[dict[str, Any]] = field(default_factory=list)


def _d(x: Any) -> date | None:
    if x is None:
        return None
    if isinstance(x, date) and not isinstance(x, datetime):
        return x
    if isinstance(x, datetime):
        return x.date()
    return date.fromisoformat(str(x)[:10])


def topic_entity(resolver: Resolver, onto: Ontology, topic_key: str) -> str:
    t = onto.topic(topic_key)
    from app.store import entities as ent

    name = t.label if t else topic_key.replace("_", " ").capitalize()
    eid = ent.by_alias(resolver.s, topic_key, "topic") or ent.by_alias(resolver.s, name, "topic")
    if eid is None:
        eid = ent.create(resolver.s, "topic", name)
    ent.add_alias(resolver.s, eid, topic_key)
    return eid


def _assertion_from_row(
    r: fstore.FactRow, src: Any, onto: Ontology, order: dict[str, int] | None = None
) -> Assertion:
    m = r.meta or {}
    return Assertion(
        key=r.origin_key,
        subject_id=r.subject_id,
        attribute=r.attribute,
        client=(r.scope or {}).get("client") or "all",
        value=r.value,
        kind=r.kind,
        statement=r.statement,
        source_id=r.source_id or "",
        source_label=src.short_label,
        source_status=src.status,
        authority_rank=onto.rank_of(src.doc_type).rank,
        asserted_from=_d(m.get("asserted_from")),
        asserted_to=_d(m.get("asserted_to")),
        scope=r.scope or {},
        position=(order or {}).get(r.passage_id or "", 0),
    )


def client_context(session: Session, onto: Ontology) -> tuple[dict[str, set[str]], list[int]]:
    """Known clients (the scopes documents declare) and the ranks of the sources declaring them."""
    scoped = [x for x in estore.list_sources(session) if x.client_scope and x.client_scope != "all"]
    known = distinctive_words({x.client_scope for x in scoped})
    return known, [onto.rank_of(x.doc_type).rank for x in scoped]


def publish(
    session: Session,
    drafts: list[Draft],
    passage_ids: list[str],
    onto: Ontology,
    compare: Comparator,
    resolver: Resolver,
    summary: str,
    episode_id: str | None = None,
    extra_groups: set[tuple[str, str]] | None = None,
) -> PublishReport:
    advisory_lock(session, f"graph-write:{tenant()}")  # one writer per tenant at a time
    now = utcnow()
    rep = PublishReport()
    known_types = [t.name for t in onto.entity_types]
    sources = estore.sources_by_ids(
        session,
        sorted(
            {d.source_id for d in drafts}
            | {r.source_id for r in fstore.live_for_passages(session, passage_ids) if r.source_id}
        ),
    )

    # 1. Entities. The client comes from the source's declared scope and the fact's own words
    # (app/graph/scope.py); declared clients are pinned, never merged into another entity.
    known, client_ranks = client_context(session, onto) if drafts else ({}, [])
    new: list[tuple[Draft, str, dict[str, Any]]] = []
    for d in drafts:
        if d.about:
            subject = resolver.resolve(d.about, norm_type(d.about_type, known_types), d.episode_id)
        else:
            subject = topic_entity(resolver, onto, d.topic)
        scope = dict(d.scope)
        src = sources.get(d.source_id)
        client = fact_client(
            d.client,
            " ".join(x for x in (d.statement, d.condition) if x),
            src.client_scope if src else None,
            known,
            infer=src is not None and infers_scope(onto.rank_of(src.doc_type).rank, client_ranks),
            condition=d.condition,
        )
        scope.pop("client", None)
        if client:
            cid = resolver.resolve(client, "client", d.episode_id, exact=client in known)
            scope["client"] = resolver.canonical_name(cid)
            scope["client_id"] = cid
        for name, typ in d.mentions:
            resolver.resolve(name, norm_type(typ, known_types), d.episode_id)
        new.append((d, subject, scope))

    # 2. Retire facts of these passages that are no longer stated.
    new_keys = {d.origin_key for d, _, _ in new}
    stale = [
        r for r in fstore.live_for_passages(session, passage_ids) if r.origin_key not in new_keys
    ]
    touched: set[tuple[str, str]] = {(r.subject_id, r.attribute) for r in stale}
    for r in stale:
        fstore.retract(session, r.id, now)
        rep.retired += 1
    touched |= {(subj, d.attribute) for d, subj, _ in new}
    touched |= extra_groups or set()

    # 3. Resolve each touched group over its own facts only.
    by_group: dict[tuple[str, str], list[tuple[Draft, str, dict[str, Any]]]] = defaultdict(list)
    for item in new:
        by_group[(item[1], item[0].attribute)].append(item)
    key_to_id: dict[str, int] = {}
    pending_supersedes: list[tuple[int, str]] = []
    group_conflicts = []
    for subject_id, attribute in sorted(touched):
        rows = {r.origin_key: r for r in fstore.related(session, subject_id, attribute)}
        extra_src = estore.sources_by_ids(
            session,
            [r.source_id for r in rows.values() if r.source_id and r.source_id not in sources],
        )
        sources.update(extra_src)
        pids = [r.passage_id for r in rows.values() if r.passage_id]
        pids += [d.passage_id for d, _, _ in by_group.get((subject_id, attribute), [])]
        order = {pid: p.ordinal for pid, p in estore.passages_by_ids(session, pids).items()}
        assertions: dict[str, Assertion] = {
            k: _assertion_from_row(r, sources[r.source_id], onto, order)
            for k, r in rows.items()
            if r.source_id in sources
        }
        new_items = {
            d.origin_key: (d, subj, sc) for d, subj, sc in by_group.get((subject_id, attribute), [])
        }
        for k, (d, subj, sc) in new_items.items():
            if k in assertions:
                continue
            src = sources[d.source_id]
            assertions[k] = Assertion(
                key=k,
                subject_id=subj,
                attribute=d.attribute,
                client=sc.get("client") or "all",
                value=d.value,
                kind=d.kind,
                statement=d.statement,
                source_id=d.source_id,
                source_label=src.short_label,
                source_status=src.status,
                authority_rank=onto.rank_of(src.doc_type).rank,
                asserted_from=d.asserted_from,
                asserted_to=d.asserted_to,
                scope=sc,
                position=order.get(d.passage_id, 0),
            )
        conflicts = resolve_group(list(assertions.values()), compare)
        for k, a in assertions.items():
            vf, vt = day_start(a.valid_from), day_start(a.valid_to)
            rep.statuses[a.status] += 1
            if k in rows:
                r = rows[k]
                if (r.status, r.valid_from, r.valid_to) == (a.status, vf, vt):
                    key_to_id[k] = r.id
                    rep.unchanged += 1
                    continue
                key_to_id[k] = fstore.revise(
                    session,
                    r.id,
                    at=now,
                    status=a.status,
                    valid_from=vf,
                    valid_to=vt,
                    meta={**(r.meta or {}), "reason": a.reason},
                )
                rep.revised += 1
            else:
                d, _subj, sc = new_items[k]
                src = sources[d.source_id]
                key_to_id[k] = fstore.insert(
                    session,
                    fstore.NewFact(
                        origin_key=k,
                        subject_id=a.subject_id,
                        attribute=a.attribute,
                        value=a.value,
                        statement=d.statement,
                        kind=d.kind,
                        status=a.status,
                        scope=sc,
                        condition=d.condition,
                        quote=d.quote,
                        passage_id=d.passage_id,
                        episode_id=d.episode_id,
                        source_id=d.source_id,
                        authority_rank=onto.rank_of(src.doc_type).rank,
                        valid_from=vf,
                        valid_to=vt,
                        confidence=1.0 if d.quote_verified else 0.5,
                        meta={
                            "asserted_from": str(d.asserted_from) if d.asserted_from else None,
                            "asserted_to": str(d.asserted_to) if d.asserted_to else None,
                            "quote_verified": d.quote_verified,
                            "topic": d.topic,
                            "reason": a.reason,
                            **d.meta,
                        },
                    ),
                    at=now,
                )
                rep.inserted += 1
            if a.supersedes_key:
                pending_supersedes.append((key_to_id[k], a.supersedes_key))
        group_conflicts += conflicts

    for fid, loser_key in pending_supersedes:
        if loser_key in key_to_id:
            fstore.set_supersedes(session, fid, key_to_id[loser_key])
    for c in group_conflicts:
        if c.a_key in key_to_id and c.b_key in key_to_id:
            cid = kb.add_conflict(
                session,
                subject_id=c.subject_id,
                attribute=c.attribute,
                scope={"client": c.client},
                fact_a=key_to_id[c.a_key],
                fact_b=key_to_id[c.b_key],
                kind=c.kind,
                authoritative_fact=key_to_id.get(c.authoritative_key or ""),
                reason=c.reason,
            )
            rep.conflicts += cid is not None

    # 4. Publish.
    if rep.inserted or rep.revised or rep.retired:
        v = kb.bump_kb_version(session, summary)
        rep.kb_version = v
        kb.record_change(
            session,
            v,
            f"{summary}: {rep.inserted} new, {rep.revised} revised, {rep.retired} retired facts",
            source_episode=episode_id,
        )
    rep.entity_decisions = resolver.decisions
    return rep
