"""The daily digest: one day's changes in one summary.

For people who do not watch the Changes page: rule changes (old -> new value, from when, from
where, how many have seen it), facts withdrawn or retired, other knowledge updates counted, what
waits for the owner's review, and for a given user the changes they have not acknowledged yet.
Also as plain text to paste into an email or a chat channel. Read-only and deterministic: no
model call. The day is the reader's local day (`utc_offset_minutes` east of UTC).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.distribute.feed import change_items
from app.store import kb
from app.store.base import utcnow


def local_today(utc_offset_minutes: int = 0) -> date:
    return (utcnow() + timedelta(minutes=utc_offset_minutes)).date()


def _bounds(day: date, utc_offset_minutes: int) -> tuple[datetime, datetime]:
    start = datetime(day.year, day.month, day.day, tzinfo=UTC) - timedelta(
        minutes=utc_offset_minutes
    )
    return start, start + timedelta(days=1)


def _when(v: Any) -> str:
    if isinstance(v, datetime | date):
        d = v.date() if isinstance(v, datetime) else v
        return f"{d.day} {d:%b %Y}"
    return str(v or "")


def build_digest(
    session: Session,
    day: date,
    utc_offset_minutes: int = 0,
    user_id: str | None = None,
    users: int = 0,
) -> dict[str, Any]:
    start, end = _bounds(day, utc_offset_minutes)
    items = change_items(session, kb.changes_between(session, start, end))
    rules = [i for i in items if i["attribute"] and i["status"] in ("confirmed", "provisional")]
    withdrawn = [i for i in items if i["attribute"] and i["status"] in ("rejected", "retired")]
    updates = [i for i in items if not i["attribute"]]
    seen = kb.acked_by(session, user_id, [i["id"] for i in rules]) if user_id else set()
    review = kb.list_review_items(session)
    out = {
        "day": day.isoformat(),
        "rules": rules,
        "withdrawn": withdrawn,
        "updates": len(updates),
        "update_summaries": [u["summary"] for u in updates][:10],
        "to_acknowledge": [i["id"] for i in rules if i["id"] not in seen] if user_id else [],
        "document_edits": [i["id"] for i in rules if i.get("document_edit")],
        "waiting_review": len(review),
        "users": users,
        "empty": not items,
    }
    out["text"] = digest_text(out)
    return out


def digest_text(d: dict[str, Any]) -> str:
    """The digest as plain text (an email body or a chat message)."""
    day = date.fromisoformat(d["day"])
    lines = [f"Changes on {day.day} {day:%b %Y}"]
    if d["empty"]:
        lines.append("No changes to the knowledge base.")
    for i in d["rules"]:
        what = f"{i['topic']}: " if i["topic"] else ""
        vals = (
            f"{i['old_value']} -> {i['new_value']}"
            if i["old_value"] and i["new_value"]
            else i["new_value"] or i["summary"]
        )
        tail = [f"from {_when(i['effective_at'])}"]
        if i["source_label"]:
            tail.append(f"source: {i['source_label']}")
        if i["status"] == "provisional":
            tail.append("provisional, awaiting the owner")
        if d["users"]:
            tail.append(f"seen by {i['acknowledged']} of {d['users']}")
        lines.append(f"- {what}{vals} ({'; '.join(tail)})")
    for i in d["withdrawn"]:
        label = "Withdrawn" if i["status"] == "rejected" else "No longer in force"
        lines.append(f"- {label}: {i['topic']}: {i['old_value'] or i['summary']}")
    if d["updates"]:
        lines.append(f"- {d['updates']} other knowledge updates (documents read, re-checks)")
    if d["document_edits"]:
        lines.append(
            f"{len(d['document_edits'])} change(s) need an edit to a document still in force "
            "(see Changes: Draft document edit)."
        )
    if d["waiting_review"]:
        lines.append(f"{d['waiting_review']} item(s) wait in the owner's review queue.")
    if d["to_acknowledge"]:
        lines.append(f"You have not acknowledged {len(d['to_acknowledge'])} of these yet.")
    return "\n".join(lines)
