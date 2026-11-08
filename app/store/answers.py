"""Answer log, escalations and in-app notifications."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.store.base import tenant, utcnow
from app.store.models import AnswerLog, Escalation, Notification

# ---------------------------------------------------------------- answers


def _jsonable(card: dict[str, Any]) -> dict[str, Any]:
    """Cards carry calculator results with dates; the JSON column stores them as ISO text."""
    return json.loads(json.dumps(card, default=str))


def log_answer(
    session: Session,
    *,
    user_id: str,
    question: str,
    client: str | None,
    as_of: date | None,
    kb_version: int,
    route: str,
    card: dict[str, Any],
    cited_fact_ids: list[int],
    cited_passage_ids: list[str],
    latency_ms: int | None,
) -> int:
    row = AnswerLog(
        tenant_id=tenant(),
        user_id=user_id,
        question=question,
        client=client,
        as_of=as_of,
        kb_version=kb_version,
        route=route,
        card=_jsonable(card),
        cited_fact_ids=cited_fact_ids,
        cited_passage_ids=cited_passage_ids,
        latency_ms=latency_ms,
    )
    session.add(row)
    session.flush()
    return int(row.id)


def update_card(session: Session, answer_id: int, card: dict[str, Any]) -> None:
    session.execute(
        update(AnswerLog)
        .where(AnswerLog.tenant_id == tenant(), AnswerLog.id == answer_id)
        .values(card=_jsonable(card))
    )


@dataclass
class AnswerRow:
    id: int
    user_id: str
    question: str
    client: str | None
    as_of: date | None
    kb_version: int
    route: str
    card: dict[str, Any]
    cited_fact_ids: list[int]
    created_at: datetime


def get_answer(session: Session, answer_id: int) -> AnswerRow | None:
    a = session.scalar(
        select(AnswerLog).where(AnswerLog.tenant_id == tenant(), AnswerLog.id == answer_id)
    )
    if a is None:
        return None
    return AnswerRow(
        a.id,
        a.user_id,
        a.question,
        a.client,
        a.as_of,
        a.kb_version,
        a.route,
        a.card,
        list(a.cited_fact_ids or []),
        a.created_at,
    )


# ---------------------------------------------------------------- escalations


@dataclass
class EscalationRow:
    id: int
    answer_id: int | None
    question: str
    client: str | None
    asked_by: str
    routed_to_role: str
    kind: str
    status: str
    found: dict[str, Any]
    expert_reply: str | None
    expert_id: str | None
    episode_id: str | None
    created_at: datetime
    answered_at: datetime | None


def _esc(e: Escalation) -> EscalationRow:
    return EscalationRow(
        e.id,
        e.answer_id,
        e.question,
        e.client,
        e.asked_by,
        e.routed_to_role,
        e.kind,
        e.status,
        dict(e.found or {}),
        e.expert_reply,
        e.expert_id,
        e.episode_id,
        e.created_at,
        e.answered_at,
    )


def create_escalation(
    session: Session,
    *,
    question: str,
    client: str | None,
    asked_by: str,
    routed_to_role: str,
    found: dict[str, Any],
    answer_id: int | None = None,
    kind: str = "question",
) -> int:
    row = Escalation(
        tenant_id=tenant(),
        answer_id=answer_id,
        question=question,
        client=client,
        asked_by=asked_by,
        routed_to_role=routed_to_role,
        kind=kind,
        status="open",
        found=found,
    )
    session.add(row)
    session.flush()
    return int(row.id)


def get_escalation(session: Session, escalation_id: int) -> EscalationRow | None:
    e = session.scalar(
        select(Escalation).where(Escalation.tenant_id == tenant(), Escalation.id == escalation_id)
    )
    return _esc(e) if e else None


def list_escalations(
    session: Session, status: str | None = "open", role: str | None = None
) -> list[EscalationRow]:
    """Oldest first, so none is forgotten."""
    q = select(Escalation).where(Escalation.tenant_id == tenant())
    if status:
        q = q.where(Escalation.status == status)
    if role:
        q = q.where(Escalation.routed_to_role == role)
    return [_esc(e) for e in session.scalars(q.order_by(Escalation.created_at, Escalation.id))]


def record_reply(
    session: Session, escalation_id: int, expert_id: str, reply: str, episode_id: str | None
) -> None:
    session.execute(
        update(Escalation)
        .where(Escalation.tenant_id == tenant(), Escalation.id == escalation_id)
        .values(
            expert_reply=reply,
            expert_id=expert_id,
            episode_id=episode_id,
            status="answered",
            answered_at=utcnow(),
        )
    )


def set_escalation(session: Session, escalation_id: int, **values: Any) -> None:
    session.execute(
        update(Escalation)
        .where(Escalation.tenant_id == tenant(), Escalation.id == escalation_id)
        .values(**values)
    )


# ---------------------------------------------------------------- notifications


def notify(
    session: Session,
    user_id: str,
    kind: str,
    body: str,
    answer_id: int | None = None,
    change_id: int | None = None,
) -> int:
    row = Notification(
        tenant_id=tenant(),
        user_id=user_id,
        kind=kind,
        body=body,
        answer_id=answer_id,
        change_id=change_id,
    )
    session.add(row)
    session.flush()
    return int(row.id)


def notifications_for(session: Session, user_id: str, unread_only: bool = False) -> list[dict]:
    q = select(Notification).where(
        Notification.tenant_id == tenant(), Notification.user_id == user_id
    )
    if unread_only:
        q = q.where(Notification.read_at.is_(None))
    return [
        {
            "id": n.id,
            "kind": n.kind,
            "body": n.body,
            "answer_id": n.answer_id,
            "change_id": n.change_id,
            "at": n.at.isoformat(),
            "read": n.read_at is not None,
        }
        for n in session.scalars(q.order_by(Notification.at.desc(), Notification.id.desc()))
    ]


def mark_read(session: Session, notification_id: int, user_id: str) -> bool:
    res = session.execute(
        update(Notification)
        .where(
            Notification.tenant_id == tenant(),
            Notification.id == notification_id,
            Notification.user_id == user_id,
        )
        .values(read_at=utcnow())
    )
    return bool(res.rowcount)


def distinct_users(session: Session) -> int:
    from sqlalchemy import func

    return (
        session.scalar(
            select(func.count(func.distinct(AnswerLog.user_id))).where(
                AnswerLog.tenant_id == tenant(), ~AnswerLog.user_id.startswith("eval")
            )
        )
        or 0
    )


def recent_answers(session: Session, limit: int = 2000) -> list[dict[str, Any]]:
    """The latest answers, for analytics (evaluation runs excluded)."""
    q = (
        select(AnswerLog)
        .where(AnswerLog.tenant_id == tenant(), ~AnswerLog.user_id.startswith("eval"))
        .order_by(AnswerLog.id.desc())
        .limit(limit)
    )
    return [
        {
            "id": a.id,
            "user_id": a.user_id,
            "question": a.question,
            "client": a.client,
            "route": a.route,
            "status": (a.card or {}).get("status"),
            "entities": (a.card or {}).get("entities") or [],
            "cited_passage_ids": list(a.cited_passage_ids or []),
            "latency_ms": a.latency_ms,
            "kb_version": a.kb_version,
            "created_at": a.created_at,
        }
        for a in session.scalars(q)
    ]
