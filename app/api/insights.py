"""Totals, usage analytics and per-user notifications."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from statistics import median
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import not_found, read_session, write_session
from app.store import answers as astore
from app.store import entities as ents
from app.store import episodes as estore
from app.store import facts as fstore
from app.store import jobs, kb

router = APIRouter(tags=["insights"])


@router.get("/stats")
def stats(s: Session = Depends(read_session)) -> dict[str, Any]:
    """What the engine holds and how busy it is (Sources page rail)."""
    summary = fstore.summary(s)
    q = jobs.counts(s)
    return {
        **estore.totals(s),
        "episodes_by_status": estore.episode_counts(s),
        "facts": sum(summary["by_status"].values()),
        "facts_by_status": summary["by_status"],
        "entities": sum(ents.count(s).values()),
        "entities_by_type": ents.count(s),
        "kb_version": kb.current_kb_version(s),
        "queue": {
            "queued": q.get("queued", 0),
            "running": q.get("running", 0),
            "failed": q.get("failed", 0),
        },
        "users": astore.distinct_users(s),
        "open_conflicts": len(kb.list_conflicts(s, status="open")),
        "open_reviews": len(kb.list_review_items(s)),
    }


HANDLED = {"closed", "resolved"}  # escalation taken out of the queue, or answered and published
# Not answered from the documents. needs_specialist is left out: the documents did answer it, by
# sending it to a named role.
GAP_STATUSES = {"unsupported", "unverified"}
SAME_QUESTION = 0.95  # embedding cosine: rewordings of one question (0.97-0.99) group together;
# different questions on the same topic ("canteen subsidy" per meal vs night shift) stay below 0.8


def _question_key(q: str) -> str:
    return re.sub(r"\s+", " ", (q or "").strip().lower()).rstrip(" ?.!")


def _embedding_groups(keys: list[str]) -> dict[str, str]:
    """Each question key -> the first key it rewords (cosine >= SAME_QUESTION)."""
    from app.core.embed import cosine, embed

    reps: list[tuple[str, list[float]]] = []
    out: dict[str, str] = {}
    for k in keys:
        vec = embed([k])[0]  # one at a time: each question is cached in-process
        rep = next((r for r, v in reps if cosine(vec, v) >= SAME_QUESTION), None)
        if rep is None:
            reps.append((k, vec))
            rep = k
        out[k] = rep
    return out


def open_gaps(
    rows: list[dict[str, Any]],
    escalations: list[Any],
    group: Callable[[list[str]], dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Questions the documents still do not answer: one row per question, rewordings included
    (its latest ask, with how often it went unanswered). A question drops off when its latest ask
    was answered, or when an escalation of it was closed or resolved after that ask."""
    keys = list(dict.fromkeys(_question_key(r["question"]) for r in rows))
    keys += [_question_key(e.question) for e in escalations if e.status in HANDLED]
    same = (group or _embedding_groups)(list(dict.fromkeys(keys)))
    handled_at: dict[str, Any] = {}
    for e in escalations:
        if e.status in HANDLED:
            g = same[_question_key(e.question)]
            handled_at[g] = max(handled_at.get(g, e.created_at), e.created_at)
    latest: dict[str, dict[str, Any]] = {}
    misses: Counter[str] = Counter()
    for r in rows:  # newest first
        g = same[_question_key(r["question"])]
        latest.setdefault(g, r)
        if r["status"] in GAP_STATUSES:
            misses[g] += 1
    out = []
    for g, r in latest.items():
        if r["status"] not in GAP_STATUSES:
            continue
        if g in handled_at and r["created_at"] <= handled_at[g]:
            continue
        out.append(
            {
                **{f: r[f] for f in ("id", "question", "client", "status", "created_at")},
                "times": misses[g],
            }
        )
    return out


@router.get("/analytics")
def analytics(s: Session = Depends(read_session)) -> dict[str, Any]:
    """Most-asked topics, unanswered questions, most-cited sources, latency and
    acknowledgement rate, from the answers log (evaluation runs excluded)."""
    rows = astore.recent_answers(s)
    topics: Counter[str] = Counter()
    cited: Counter[str] = Counter()
    for r in rows:
        for e in r["entities"]:
            if e.get("type") == "topic" and e.get("name"):
                topics[e["name"]] += 1
        cited.update(r["cited_passage_ids"])
    passages = estore.passages_by_ids(s, [pid for pid, _ in cited.most_common(8)])
    srcs = estore.sources_by_ids(s, sorted({p.source_id for p in passages.values()}))
    latencies = [r["latency_ms"] for r in rows if r["latency_ms"]]
    changes = kb.changes_since(s, 0, limit=500)
    acks = kb.ack_counts(s, [c.id for c in changes])
    users = astore.distinct_users(s)
    return {
        "answers": len(rows),
        "users": users,
        "by_status": dict(Counter(r["status"] or "unknown" for r in rows)),
        "by_route": dict(Counter(r["route"] for r in rows)),
        "top_topics": [{"topic": t, "count": n} for t, n in topics.most_common(8)],
        "unanswered": open_gaps(rows, astore.list_escalations(s, status=None))[:12],
        "top_sources": [
            {
                "passage_id": pid,
                "count": n,
                "label": (
                    srcs[passages[pid].source_id].short_label
                    if pid in passages and passages[pid].source_id in srcs
                    else pid
                ),
                "locator": passages[pid].locator if pid in passages else "",
                "section_title": passages[pid].section_title if pid in passages else "",
            }
            for pid, n in cited.most_common(8)
        ],
        "latency_ms": {
            "p50": int(median(latencies)) if latencies else None,
            "p90": int(sorted(latencies)[int(0.9 * (len(latencies) - 1))]) if latencies else None,
        },
        "acknowledgements": {
            "changes": len(changes),
            "acks": sum(acks.values()),
            "rate": (sum(acks.values()) / (len(changes) * users)) if changes and users else None,
        },
    }


@router.get("/notifications")
def notifications(
    user_id: str, unread: bool = True, s: Session = Depends(read_session)
) -> list[dict[str, Any]]:
    """A user's notifications (an expert answered their question, a rule they used changed)."""
    return astore.notifications_for(s, user_id, unread_only=unread)


class ReadIn(BaseModel):
    user_id: str


@router.post("/notifications/{notification_id}/read")
def mark_read(
    notification_id: int, body: ReadIn, s: Session = Depends(write_session)
) -> dict[str, Any]:
    if not astore.mark_read(s, notification_id, body.user_id):
        raise not_found("notification")
    return {"id": notification_id, "read": True}
