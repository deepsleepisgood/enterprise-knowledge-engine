"""Holding a governed change and applying the owner's decision on it.

hold():  after extraction, the episode's facts are stored as provisional or pending (by
         `policy.decide`), its sources take that status (so pending text is never retrieved as
         evidence), and a `change` review item goes to the owner.
apply_decision() (worker job `apply_review`):
    approve  the facts become ordinary facts and their groups are resolved as usual (authority,
             scope, dates); a deferred version link is made; escalated questions are re-asked.
             The change records the episode, the sender and the reviewer.
    reject   the facts are retracted (kept, never deleted) and the sources marked rejected.
A `retire` item (passages a new version dropped) is applied on approval too.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.db import session_scope
from app.govern.policy import PENDING, Verdict, change_payload
from app.store import episodes as estore
from app.store import facts as fstore
from app.store import jobs, kb
from app.worker import handler


def hold(
    s: Session,
    episode_id: str,
    verdict: Verdict,
    fact_ids: list[int],
    retire: list[int] | None = None,
) -> int | None:
    """Mark a governed episode's sources and open the review item. Returns its id.
    `retire`: facts the change replaces (retired when it is approved, kept if rejected)."""
    ep = estore.get_episode(s, episode_id)
    if ep is None or not fact_ids:
        return None
    sources = estore.list_sources(s, episode_id)
    was = {x.id: x.status for x in sources}
    for x in sources:
        estore.update_source(s, x.id, status=verdict.status)
    facts = sorted(fstore.by_ids(s, fact_ids).values(), key=lambda f: f.id)
    payload = change_payload(
        ep, verdict, [x.id for x in sources], facts, [x.short_label for x in sources]
    )
    payload["source_status"] = was
    payload["defer_versions"] = bool((ep.meta or {}).get("defer_versions"))
    if retire:
        payload["retire_fact_ids"] = list(retire)
    item = kb.add_review_item(
        s, "change", payload, risk_tier="high" if verdict.high_risk else "normal"
    )
    estore.set_status(s, episode_id, "pending_review")
    return item


def _approve(s: Session, p: dict[str, Any], by: str) -> dict[str, Any]:
    from app.graph.compare import LLMComparator, deterministic
    from app.graph.entities import Resolver
    from app.graph.pipeline import _default_structured, active_ontology
    from app.graph.write import governed, publish
    from app.ingest import versions

    onto = active_ontology(s)
    if onto is None:
        return {"skipped": "no frozen schema"}
    live = [f for f in fstore.by_ids(s, p.get("fact_ids") or []).values() if f.retracted_at is None]
    for fid in p.get("retire_fact_ids") or []:  # what the approved change replaces
        fstore.retract(s, fid)
    groups: set[tuple[str, str]] = set()
    for f in live:
        if not governed(f.meta):
            continue
        meta = {k: v for k, v in (f.meta or {}).items() if k != "governance"}
        fstore.revise(
            s,
            f.id,
            status="current",
            meta={**meta, "approved_by": by, "reason": f"approved by {by}"},
        )
        groups.add((f.subject_id, f.attribute))
    # Approved content is in force; only a record (interview, observation) keeps its status.
    for sid, status in (p.get("source_status") or {}).items():
        estore.update_source(s, sid, status="record" if status == "record" else "current")
    if p.get("defer_versions"):
        for sid in p.get("source_ids") or []:
            for link in versions.link_versions(s, sid):
                jobs.enqueue(s, "reresolve_source", {"source_id": link.older_id})
    structured = _default_structured()
    who = p.get("sender_role") or p.get("sender") or "unknown sender"
    rep = publish(
        s,
        [],
        [],
        onto,
        LLMComparator(structured) if structured else deterministic,
        Resolver(s, structured_fn=structured),
        summary=f"{len(groups)} rules from {p.get('channel')} by {who}, approved by {by}",
        episode_id=p.get("episode_id"),
        extra_groups=groups,
    )
    kbv = rep.kb_version
    if kbv is None:  # the approval itself changed what is in force: always record it
        kbv = kb.bump_kb_version(s, f"change approved by {by}")
    kb.record_change(
        s,
        kbv,
        f"{len(live)} facts from {p.get('channel')} by {who} approved by {by}",
        source_episode=p.get("episode_id"),
    )
    if p.get("episode_id"):
        estore.set_status(s, p["episode_id"], "published")
        jobs.enqueue_once(s, "index_embeddings", {})
        if p.get("channel") == "expert_answer":
            jobs.enqueue(s, "reask_escalations", {"episode_id": p["episode_id"]})
    return {"approved": len(groups), "kb_version": kbv}


def _reject(s: Session, p: dict[str, Any], by: str) -> dict[str, Any]:
    live = [f for f in fstore.by_ids(s, p.get("fact_ids") or []).values() if f.retracted_at is None]
    for f in live:
        fstore.retract(s, f.id)
    for sid in p.get("source_ids") or []:
        estore.update_source(s, sid, status="rejected", status_note=f"rejected by {by}")
    if p.get("episode_id"):
        estore.set_status(s, p["episode_id"], "rejected")
    out: dict[str, Any] = {"retracted": len(live)}
    if live and p.get("status") != PENDING:  # provisional facts were answerable: record it
        v = kb.bump_kb_version(s, f"provisional change rejected by {by}")
        kb.record_change(
            s,
            v,
            f"{len(live)} provisional facts rejected by {by}",
            source_episode=p.get("episode_id"),
        )
        out["kb_version"] = v
    return out


def _retire(s: Session, p: dict[str, Any], by: str) -> dict[str, Any]:
    pids = p.get("passage_ids") or []
    live = fstore.live_for_passages(s, pids)
    for f in live:
        fstore.retract(s, f.id)
    estore.retire_passages(s, pids)
    if live:
        v = kb.bump_kb_version(s, f"{len(live)} facts retired, approved by {by}")
        kb.record_change(s, v, f"{len(pids)} passages retired by {by}")
    return {"retired": len(live)}


def apply_decision(item_id: int) -> dict[str, Any]:
    with session_scope() as s:
        item = kb.get_review_item(s, item_id)
        if item is None:
            return {"skipped": "no such item"}
        p, by = dict(item.payload or {}), item.decided_by or "owner"
        if item.kind == "change" and item.status == "approved":
            return _approve(s, p, by)
        if item.kind == "change" and item.status == "rejected":
            return _reject(s, p, by)
        if item.kind == "retire" and item.status == "approved":
            return _retire(s, p, by)
    return {"skipped": f"nothing to apply for {item.kind} / {item.status}"}


@handler("apply_review")
def apply_review_job(payload: dict[str, Any]) -> dict[str, Any]:
    return apply_decision(int(payload["item_id"]))
