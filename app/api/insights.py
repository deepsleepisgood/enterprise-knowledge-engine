"""Totals, usage analytics and per-user notifications."""

from __future__ import annotations

from collections import Counter
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
ABSTAINED = {"unsupported", "unverified", "needs_specialist"}


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
        "unanswered": [
            {k: r[k] for k in ("id", "question", "client", "status", "created_at")}
            for r in rows
            if r["status"] in ABSTAINED
        ][:12],
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
