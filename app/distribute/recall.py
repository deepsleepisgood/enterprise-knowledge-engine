"""Answer recall: when a rule someone relied on changes, tell them.

A change that retires or replaces a fact names it as `old_fact`. Everyone who, in the 7 days
before that change, got an answer citing any version of the fact (the rows sharing its origin key:
a revision has a new id) gets one notification per change, linking their latest such answer.
Answers about a past date (`as_of`), evaluation runs and anonymous askers (nobody to tell) are not
recalled. Re-running is safe: nobody is told twice about the same change.

Runs as the worker job `answer_recall`, queued by `kb.record_change` in the same transaction
that publishes the change.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.db import session_scope
from app.store import answers as astore
from app.store import facts as fstore
from app.store import kb
from app.store.base import utcnow
from app.worker import handler

WINDOW = timedelta(days=7)
KIND = "recall"
ANONYMOUS = "anonymous"  # the API's default asker: there is nobody to notify


def _body(summary: str, question: str) -> str:
    what = summary.strip().rstrip(".")
    asked = question.strip()
    asked = asked if len(asked) <= 120 else asked[:117] + "..."
    return f'A rule your answer relied on has changed: {what}. You asked: "{asked}"'


def recall(session: Session, now: datetime | None = None) -> dict[str, Any]:
    now = now or utcnow()
    changes = kb.changes_retiring(session, since=now - WINDOW)
    lineages = fstore.lineage_ids(session, sorted({c.old_fact for c in changes if c.old_fact}))
    sent: list[int] = []
    for c in changes:
        ids = lineages.get(c.old_fact or -1) or {c.old_fact}
        cited = astore.answers_citing(
            session, sorted(i for i in ids if i), since=c.created_at - WINDOW, until=c.created_at
        )
        latest = {a.user_id: a for a in cited if a.user_id != ANONYMOUS}  # ordered by id
        for a in latest.values():
            if astore.already_notified(session, a.user_id, KIND, c.id):
                continue
            sent.append(
                astore.notify(
                    session,
                    a.user_id,
                    KIND,
                    _body(c.summary, a.question),
                    answer_id=a.id,
                    change_id=c.id,
                )
            )
    return {"changes": len(changes), "notified": len(sent)}


@handler("answer_recall")
def answer_recall(payload: dict[str, Any]) -> dict[str, Any]:
    with session_scope() as s:
        return recall(s)
