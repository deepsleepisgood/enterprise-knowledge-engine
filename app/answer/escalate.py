"""Escalation to an expert, and the "Report a wrong answer" button (BUILD_PLAN Phase 4).

An expert's reply is input, not a rule (CLAUDE.md rule 13): the asker sees it at once, labelled
as not yet part of the knowledge base, and it enters the pipeline as an `expert_answer` episode
that goes through the same triage, extraction and governance as an email. Once facts from it are
published, the question is asked again and the asker is notified.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.answer.card import PROCESS_OWNER
from app.core.db import session_scope
from app.ingest.connectors import from_text
from app.ingest.intake import submit
from app.store import answers as astore
from app.store import facts as fstore
from app.store import kb
from app.worker import handler

EXPERT_LABEL = "Expert reply — not yet part of the knowledge base"


def _found(card: dict[str, Any]) -> dict[str, Any]:
    diag = card.get("diagnostics") or {}
    return {
        "status": card.get("status"),
        "reason": (card.get("route_to") or {}).get("reason"),
        "passages": (diag.get("retrieval") or {}).get("passages", []),
        "top_score": (diag.get("retrieval") or {}).get("top_score"),
        "verifier": diag.get("verifier"),
    }


def escalate(
    answer_id: int, asked_by: str, role: str | None = None, kind: str = "question"
) -> dict[str, Any]:
    """Send an answered (or abstained) question to the routed role."""
    with session_scope() as s:
        a = astore.get_answer(s, answer_id)
        if a is None:
            raise LookupError(f"answer {answer_id} not found")
        role = role or (a.card.get("route_to") or {}).get("role") or PROCESS_OWNER
        eid = astore.create_escalation(
            s,
            question=a.question,
            client=a.client,
            asked_by=asked_by,
            routed_to_role=role,
            found=_found(a.card),
            answer_id=answer_id,
            kind=kind,
        )
        if kind == "report":
            kb.add_review_item(
                s,
                "report",
                {
                    "escalation_id": eid,
                    "answer_id": answer_id,
                    "question": a.question,
                    "reported_by": asked_by,
                },
            )
    return {"escalation_id": eid, "routed_to": role, "message": f"Sent to {role}"}


def report_wrong(answer_id: int, user_id: str, note: str = "") -> dict[str, Any]:
    out = escalate(answer_id, user_id, role=PROCESS_OWNER, kind="report")
    if note:
        with session_scope() as s:
            esc = astore.get_escalation(s, out["escalation_id"])
            if esc:
                astore.set_escalation(s, esc.id, found={**esc.found, "note": note})
    return out


def reply(
    escalation_id: int,
    expert_id: str,
    text: str,
    expert_role: str | None = None,
    effective: date | None = None,
    scope: str | None = None,
) -> dict[str, Any]:
    """Record an expert's reply, deliver it to the asker, and ingest it as an episode."""
    with session_scope() as s:
        e = astore.get_escalation(s, escalation_id)
        if e is None:
            raise LookupError(f"escalation {escalation_id} not found")
        body = f"Question: {e.question}\n\nAnswer from {expert_id}:\n{text}"
        ep = from_text(
            body,
            channel="expert_answer",
            sender=expert_id,
            subject=f"Expert answer: {e.question[:80]}",
            sender_role=expert_role or e.routed_to_role,
            effective_hint=effective,
            scope_hint=scope or e.client,
        )
        episode_id, _ = submit(s, ep)
        astore.record_reply(s, escalation_id, expert_id, text, episode_id)
        astore.notify(
            s, e.asked_by, "expert_reply", f"{EXPERT_LABEL}: {text}", answer_id=e.answer_id
        )
    return {"escalation_id": escalation_id, "episode_id": episode_id, "label": EXPERT_LABEL}


def reask_if_published(episode_id: str, **ask_kw: Any) -> list[dict[str, Any]]:
    """After an expert-answer episode is extracted: if any of its facts is now in force, ask the
    original question again and notify the asker. Pending facts wait for the owner."""
    from app.answer.pipeline import ask

    with session_scope() as s:
        waiting = [
            e for e in astore.list_escalations(s, status="answered") if e.episode_id == episode_id
        ]
        live = fstore.live_for_episode(s, episode_id, statuses=["current", "provisional"])
    if not waiting or not live:
        return []
    out = []
    for e in waiting:
        card = ask(e.question, client=e.client, user_id=e.asked_by, **ask_kw)
        with session_scope() as s:
            astore.set_escalation(
                s, e.id, status="resolved", resulting_fact_ids=[f.id for f in live]
            )
            astore.notify(
                s,
                e.asked_by,
                "reanswered",
                "Your question has a new answer from the knowledge base.",
                answer_id=int(card["answer_id"]),
            )
        out.append(card)
    return out


@handler("reask_escalations")
def reask_job(payload: dict[str, Any]) -> dict[str, Any]:
    cards = reask_if_published(payload["episode_id"])
    return {"reasked": [c["answer_id"] for c in cards]}
