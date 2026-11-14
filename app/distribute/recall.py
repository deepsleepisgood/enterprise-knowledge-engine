"""Answer recall: when a rule someone relied on changes, tell them.

A change that retires or replaces a fact names it as `old_fact`. Everyone who, from 7 days before
that change on, got an answer citing a row the change replaced gets one notification per change,
linking their latest such answer. Answers about a past date (`as_of`), evaluation runs and
anonymous askers (nobody to tell) are not recalled. Re-running is safe: nobody is told twice
about the same change.

"A row the change replaced" is a version of the fact (the rows sharing its origin key: a revision
has a new id) that is retracted and no newer than `old_fact`: the row the change retracted, or an
earlier version. An answer can only cite such a row as in force if it read the knowledge base
before the change, so this holds whenever the answer was saved, including an answer still being
written when the change was published, and whatever order concurrent publishes committed in
(kb version numbers do not follow commit order). A later revision of the same fact, cited by an
answer that saw the change, is newer than `old_fact` and is not recalled. The answer path queues
this job again when it saves an answer while something was published (`pipeline.ask`), since
the job queued by the change may have run before that answer existed.

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
    rows = fstore.by_ids(session, sorted({i for ids in lineages.values() for i in ids}))
    sent: list[int] = []
    for c in changes:
        if not c.old_fact:
            continue
        ids = lineages.get(c.old_fact) or {c.old_fact}
        replaced = sorted(
            i for i in ids if i <= c.old_fact and i in rows and rows[i].retracted_at is not None
        )
        cited = astore.answers_citing(session, replaced, since=c.created_at - WINDOW)
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
