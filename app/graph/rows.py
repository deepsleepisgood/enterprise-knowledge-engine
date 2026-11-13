"""Facts from data rows: a plug-in says which cells of a spreadsheet are statements about an
entity (a column of free-text notes about each counterparty, say), and the core writes them as
facts that cite the exact row.

No language model is involved: the plug-in knows the columns, the core knows the graph. Each
row's fact has a stable origin (`row:<passage id>:<attribute>`), so loading the same export again
changes nothing, a changed note retires the old fact and adds the new one (with a change notice),
and a note that is gone is retired. Facts are never deleted.

Approval: an owner's own seeding is published directly (`approved=True`); otherwise the facts are
held as pending and a review item goes to the owner, as for any governed episode.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.graph.ontology import Ontology
from app.store import entities as ents
from app.store import episodes as estore
from app.store import facts as fstore
from app.store import jobs, kb
from app.store.base import day_start, utcnow

ORIGIN = "row:"


@dataclass
class RowFact:
    """One statement a plug-in read from a data row."""

    subject: str  # the entity's display name (unique within its type)
    subject_type: str
    statement: str
    locator: str  # the row passage's locator in this episode, e.g. "sheet row 12"
    attribute: str  # a schema attribute key, or a plain name (stored as other:<name>)
    aliases: list[str] = field(default_factory=list)
    kind: str = "practice"
    attrs: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RowFact:
        return cls(
            subject=str(d["subject"]),
            subject_type=str(d["subject_type"]),
            statement=str(d["statement"]),
            locator=str(d["locator"]),
            attribute=str(d["attribute"]),
            aliases=[str(a) for a in d.get("aliases") or []],
            kind=str(d.get("kind") or "practice"),
            attrs=dict(d.get("attrs") or {}),
        )


def _attribute(onto: Ontology | None, key: str) -> str:
    if onto is not None and onto.attribute(key) is not None:
        return key
    return key if key.startswith("other:") else f"other:{key}"


def _when(session: Session, episode_id: str | None, cache: dict[str, tuple]) -> tuple:
    """When an export was taken, to order exports: its sources' date, then when it arrived."""
    key = episode_id or ""
    if key not in cache:
        ep = estore.get_episode(session, key) if key else None
        dated = [x.dated for x in estore.list_sources(session, key) if x.dated] if key else []
        got = ep.received_at if ep is not None else None
        day = max(dated) if dated else (got.date() if got else None)
        cache[key] = (day.isoformat() if day else "", got.isoformat() if got else "", key)
    return cache[key]


def publish_row_facts(
    session: Session,
    onto: Ontology | None,
    episode_id: str,
    items: list[RowFact],
    approved: bool,
    by: str = "owner",
) -> dict[str, Any]:
    """Write one episode's row facts (one transaction: the caller's session). Returns counts.

    An export is a full picture of the columns it covers: for each attribute it carries, facts
    an earlier export (another file) gave for that attribute are replaced. A row about the same
    entity moves to cite the new file (with a change notice if the note changed); an entity the
    new export has no note for is retired. An export older than one already loaded for those
    attributes changes nothing. A held (unapproved) export retires nothing until approved.
    """
    rows = {p.locator: p for p in estore.passages_for_episode(session, episode_id)}
    sources = {s.id: s for s in estore.list_sources(session, episode_id)}
    out: dict[str, Any] = {
        "added": 0,
        "changed": 0,
        "unchanged": 0,
        "carried": 0,
        "retired": 0,
        "missing_rows": [],
        "held": 0,
    }
    wanted: dict[str, tuple[RowFact, Any]] = {}
    for it in items:
        p = rows.get(it.locator)
        if p is None:
            out["missing_rows"].append(it.locator)
            continue
        attr = _attribute(onto, it.attribute)
        wanted[f"{ORIGIN}{p.id}:{attr}"] = (it, p)
    attrs = {_attribute(onto, it.attribute) for it, _ in wanted.values()}
    every = fstore.live_with_origin_prefix(session, ORIGIN)
    # Facts other exports gave for the same attributes: earlier ones are replaced by this one.
    when: dict[str, tuple] = {}
    mine = _when(session, episode_id, when)
    others = [f for f in every if f.source_id not in sources and f.attribute in attrs]
    newer = sorted(
        {f.episode_id or "" for f in others if _when(session, f.episode_id, when) > mine}
    )
    if newer:
        out["stale"] = newer  # a later export of these columns is already loaded
        return out
    earlier = {(f.subject_id, f.attribute): f for f in others}
    live = fstore.live_by_origin(session, list(wanted))
    status = "current" if approved else "pending"
    meta: dict[str, Any] = {"origin": "data row"}
    if approved:
        meta["approved_by"] = by
    else:
        meta.update(governance="pending", reason="from a data export: held for the process owner")
    new_ids: list[int] = []
    swaps: list[tuple[int, int, str]] = []
    replaced: list[int] = []  # earlier exports' facts this export replaces
    now = utcnow()
    for key, (it, p) in wanted.items():
        old = live.get(key)
        if old is not None and old.statement == it.statement:
            out["unchanged"] += 1
            continue
        attr = _attribute(onto, it.attribute)
        src = sources.get(p.source_id)
        sid = ents.create(
            session, it.subject_type, it.subject, attrs=it.attrs, episode_id=episode_id
        )
        for a in it.aliases:
            ents.add_alias(session, sid, a, episode_id)
        prev = old if old is not None else earlier.pop((sid, attr), None)
        if old is not None:
            fstore.retract(session, old.id, at=now)
        elif prev is not None:
            replaced.append(prev.id)
        fid = fstore.insert(
            session,
            fstore.NewFact(
                origin_key=key,
                subject_id=sid,
                attribute=attr,
                value={"type": "text", "text": it.statement},
                statement=it.statement,
                kind=it.kind,
                status=status,
                quote=it.statement,
                passage_id=p.id,
                episode_id=episode_id,
                source_id=p.source_id,
                authority_rank=(src.authority_rank if src and src.authority_rank else 99),
                valid_from=day_start(src.dated) if src and src.dated else None,
                supersedes_id=prev.id if prev is not None else None,
                meta=dict(meta),
            ),
            at=now,
        )
        new_ids.append(fid)
        if prev is None:
            out["added"] += 1
        elif prev.statement == it.statement:
            out["carried"] += 1  # the same note, now cited from the newer export
        else:
            out["changed"] += 1
            swaps.append((fid, prev.id, f"{it.subject}: {prev.statement} -> {it.statement}"))
    # Notes no longer in this export, and earlier exports' notes it has no row for: retired,
    # never deleted. Earlier exports' facts go now if approved, else when the owner approves.
    gone_here = [f for f in every if f.source_id in sources and f.origin_key not in wanted]
    for f in gone_here:
        fstore.retract(session, f.id, at=now)
    replaced += [f.id for f in earlier.values()]
    out["retired"] = len(gone_here) + len(earlier)
    if approved:
        for fid in replaced:
            fstore.retract(session, fid, at=now)
    if not new_ids and not out["retired"]:
        return out
    if approved:
        v = kb.bump_kb_version(
            session,
            f"data rows of episode {episode_id}: {out['added']} new, {out['changed']} changed, "
            f"{out['carried']} carried over, {out['retired']} retired facts",
        )
        for new, old, text in swaps:
            kb.record_change(
                session, v, text, new_fact=new, old_fact=old, source_episode=episode_id
            )
        for f in earlier.values():
            kb.record_change(
                session,
                v,
                f"Retired: {f.statement} (not in the newer export)",
                old_fact=f.id,
                source_episode=episode_id,
            )
        kb.record_change(
            session,
            v,
            f"{out['added'] + out['changed'] + out['carried']} facts from data rows "
            f"published by {by}",
            source_episode=episode_id,
        )
    elif new_ids:
        from app.govern.apply import hold
        from app.govern.policy import Verdict

        hold(
            session,
            episode_id,
            Verdict(status="pending", reasons=[meta["reason"]]),
            new_ids,
            retire=replaced,
        )
        out["held"] = len(new_ids)
    jobs.enqueue_once(session, "index_embeddings", {})
    return out
