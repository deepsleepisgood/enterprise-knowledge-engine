"""Teams chat export (JSON) -> one episode per conversation thread.

Reads the Microsoft Graph `chatMessage` shape that Teams exports and the Graph API return:
`{"value": [...]}` or `{"messages": [...]}` or a bare list, each message with `id`, `replyToId`,
`messageType`, `createdDateTime`, `from.user.displayName` and `body.content` (HTML or text).
Optional extras: `from.user.jobTitle` (the sender's role), and top-level `team`, `channel` or
`topic` naming where the export came from, and `members: [{displayName, jobTitle}]`.

A thread is a channel post with its replies; messages of a chat (no replies) are grouped into
conversations split at gaps of more than CHAT_GAP. Each thread becomes a short chat transcript,
one turn per message (`[HH:MM] Name: text`), so passages cite the message time and speaker.
System messages, deleted messages and empty bodies are skipped. The title never quotes message
text: a message mentioning a "policy" must not make the thread look like a policy document.

Threads go through triage like emails (app/ingest/triage.py): questions are recorded, not
answered again; tips and rule claims are extracted and held for the owner.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

CHANNEL = "teams"
CHAT_GAP = timedelta(hours=4)
_SKIP_TYPES = {"systemEventMessage", "unknownFutureValue", "chatEvent", "typing"}


@dataclass
class Message:
    id: str
    reply_to: str | None
    at: datetime
    author: str
    role: str | None
    text: str
    chat: str | None


def _when(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def _text(body: Any) -> str:
    """Plain text of a message body (HTML or text), blank lines collapsed."""
    if isinstance(body, str):
        content, kind = body, "text"
    else:
        content, kind = str((body or {}).get("content") or ""), (body or {}).get("contentType")
    if kind == "html" or re.search(r"<[a-zA-Z/][^>]*>", content):
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(content, "html.parser")
        for br in soup.find_all("br"):
            br.replace_with("\n")
        for p in soup.find_all(["p", "div", "li"]):
            p.insert_after("\n")
        content = soup.get_text()
    lines = [" ".join(x.split()) for x in content.replace("\r", "").split("\n")]
    return "\n".join(x for x in lines if x)


def _messages(obj: Any) -> list[dict[str, Any]] | None:
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        for key in ("value", "messages"):
            if isinstance(obj.get(key), list):
                return obj[key]
    return None


def is_teams_export(data: bytes) -> bool:
    """A JSON file of chat messages in the Graph shape (body + from + createdDateTime)."""
    head = data.lstrip()[:1]
    if head not in (b"{", b"["):
        return False
    try:
        msgs = _messages(json.loads(data.decode("utf-8-sig")))
    except (ValueError, UnicodeDecodeError):
        return False
    if not msgs:
        return False
    sample = [m for m in msgs[:20] if isinstance(m, dict)]
    return bool(sample) and all(
        "body" in m and "createdDateTime" in m and ("from" in m or "messageType" in m)
        for m in sample
    )


def _roster(obj: Any) -> dict[str, str]:
    members = obj.get("members") if isinstance(obj, dict) else None
    return {
        str(m.get("displayName")): str(m.get("jobTitle"))
        for m in members or []
        if isinstance(m, dict) and m.get("displayName") and m.get("jobTitle")
    }


def parse(obj: Any) -> list[Message]:
    roster = _roster(obj)
    out = []
    for m in _messages(obj) or []:
        if not isinstance(m, dict) or m.get("deletedDateTime"):
            continue
        if m.get("messageType") in _SKIP_TYPES:
            continue
        at = _when(m.get("createdDateTime"))
        text = _text(m.get("body"))
        if at is None or not text:
            continue
        frm = m.get("from") or {}
        user = frm.get("user") or frm.get("application") or {}
        author = str(user.get("displayName") or "Unknown").strip()
        out.append(
            Message(
                id=str(m.get("id") or f"{at.isoformat()}-{len(out)}"),
                reply_to=str(m["replyToId"]) if m.get("replyToId") else None,
                at=at,
                author=author,
                role=user.get("jobTitle") or roster.get(author),
                text=text,
                chat=m.get("chatId") or (m.get("channelIdentity") or {}).get("channelId"),
            )
        )
    return sorted(out, key=lambda x: x.at)


def threads(msgs: list[Message]) -> list[list[Message]]:
    """Channel posts with their replies; chats split into conversations at long gaps."""
    by_id = {m.id: m for m in msgs}
    roots: dict[str, list[Message]] = {}
    loose: list[Message] = []
    for m in msgs:
        if m.reply_to and m.reply_to in by_id:
            roots.setdefault(m.reply_to, []).append(m)
        elif m.reply_to:
            loose.append(m)  # a reply whose post is not in the export: its own thread
        else:
            roots.setdefault(m.id, [])
    has_replies = any(roots.values())
    out: list[list[Message]] = []
    if has_replies:
        out = [[by_id[r], *roots[r]] for r in roots]
    else:  # a chat: consecutive messages are one conversation until a long pause
        current: list[Message] = []
        for m in (by_id[r] for r in roots):
            if current and (m.at - current[-1].at > CHAT_GAP or m.chat != current[-1].chat):
                out.append(current)
                current = []
            current.append(m)
        if current:
            out.append(current)
    out += [[m] for m in loose]
    return sorted(out, key=lambda t: t[0].at)


def _speaker(name: str) -> str:
    """A name the transcript turn format accepts: letters, digits, spaces, . ' -"""
    s = re.sub(r"[^\w.'\- ]+", " ", name)
    s = re.sub(r"\s+", " ", s).strip()[:40] or "Unknown"
    return s[0].upper() + s[1:]


def render(thread: list[Message], where: str) -> str:
    first = thread[0]
    names = list(dict.fromkeys(m.author for m in thread))
    head = (
        f"# Teams thread — {where}\n\n"
        f"| Title | Teams thread — {where} |\n| --- | --- |\n"
        f"| Date | {first.at.date().isoformat()} |\n"
        f"| Channel | {where} |\n"
        f"| Participants | {', '.join(names)} |\n\n"
    )
    lines, day = [], first.at.date()
    for m in thread:
        if m.at.date() != day:
            day = m.at.date()
            lines.append(f"On {day.isoformat()}:")
        # One line per message: a line break inside a turn would start a new paragraph that
        # the transcript reader no longer counts as part of this message.
        said = " ".join(m.text.split("\n"))
        lines.append(f"[{m.at:%H:%M}] {_speaker(m.author)}: {said}")
    return head + "\n\n".join(lines) + "\n"


def from_teams_export(data: bytes, filename: str, **kw: Any) -> list[Any]:
    """One `teams` episode per thread, dated when it started, sent by whoever started it."""
    from app.ingest.connectors import EpisodeIn

    obj = json.loads(data.decode("utf-8-sig"))
    where = "Teams"
    if isinstance(obj, dict):
        bits = [str(obj[k]) for k in ("team", "channel", "topic") if obj.get(k)]
        where = " / ".join(bits) or where
    stem = re.sub(r"\.json$", "", filename, flags=re.I)
    uploader = kw.pop("sender", None)
    role = kw.pop("sender_role", None)
    out = []
    for t in threads(parse(obj)):
        first = t[0]
        out.append(
            EpisodeIn(
                channel=CHANNEL,
                data=render(t, where).encode("utf-8"),
                filename=f"{stem}#{first.id}.md",
                received_at=first.at,
                sender=first.author,
                sender_role=first.role,
                meta={
                    "teams": {
                        "thread": first.id,
                        "where": where,
                        "messages": len(t),
                        "participants": list(dict.fromkeys(m.author for m in t)),
                        "export": filename,
                        **({"uploaded_by": uploader} if uploader else {}),
                        **({"uploader_role": role} if role else {}),
                    }
                },
                **kw,
            )
        )
    return out
