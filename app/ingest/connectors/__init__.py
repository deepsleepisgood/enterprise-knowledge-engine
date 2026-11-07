"""Connectors turn whatever arrives (files, folders, zips, raw text, emails) into `EpisodeIn`s.

All of them go through the same intake (`app/ingest/intake.py`).
"""

from __future__ import annotations

import email
import io
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from email import policy
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path
from typing import Any

SKIP_NAMES = {".ds_store", "thumbs.db", "desktop.ini"}


@dataclass
class EpisodeIn:
    channel: str  # upload, api, email, expert_answer, watched_folder, replay
    data: bytes
    filename: str
    received_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    sender: str | None = None
    sender_role: str | None = None
    effective_hint: date | None = None
    scope_hint: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


def _skip(name: str) -> bool:
    base = Path(name).name.lower()
    return base in SKIP_NAMES or base.startswith(("~$", "._")) or not base


def from_upload(name: str, data: bytes, **kw: Any) -> list[EpisodeIn]:
    """One uploaded file; a zip expands to one episode per member."""
    if data.startswith(b"PK\x03\x04") and name.lower().endswith(".zip"):
        out = []
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for info in zf.infolist():
                if info.is_dir() or _skip(info.filename):
                    continue
                out.append(
                    EpisodeIn(
                        channel="upload",
                        data=zf.read(info),
                        filename=f"{name}/{info.filename}",
                        **kw,
                    )
                )
        return out
    if _skip(name):
        return []
    return [EpisodeIn(channel="upload", data=data, filename=name, **kw)]


def from_paths(paths: list[Path], **kw: Any) -> list[EpisodeIn]:
    """Files and folders (recursive) from disk, in a stable order."""
    out: list[EpisodeIn] = []
    for p in paths:
        files = sorted(x for x in p.rglob("*") if x.is_file()) if p.is_dir() else [p]
        for f in files:
            out += from_upload(f.name, f.read_bytes(), **kw)
    return out


def from_text(
    text: str,
    *,
    channel: str = "api",
    sender: str | None = None,
    received_at: datetime | None = None,
    subject: str | None = None,
    **kw: Any,
) -> EpisodeIn:
    body = f"# {subject}\n\n{text}" if subject else text
    return EpisodeIn(
        channel=channel,
        data=body.encode("utf-8"),
        filename=f"{channel}-message.md",
        sender=sender,
        received_at=received_at or datetime.now(UTC),
        **kw,
    )


def from_eml(raw: bytes, channel: str = "email", **kw: Any) -> list[EpisodeIn]:
    """An RFC 822 message: the message itself plus one episode per attachment."""
    msg = email.message_from_bytes(raw, policy=policy.default)
    sender = parseaddr(str(msg.get("From", "")))[1] or None
    try:
        received = parsedate_to_datetime(str(msg.get("Date")))
        received = received if received.tzinfo else received.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        received = datetime.now(UTC)
    subject = str(msg.get("Subject", "") or "message")
    name = f"{subject[:60]}.eml"
    out = [
        EpisodeIn(
            channel=channel, data=raw, filename=name, sender=sender, received_at=received, **kw
        )
    ]
    for part in msg.iter_attachments():
        fname = part.get_filename()
        payload = part.get_payload(decode=True)
        if fname and payload and not _skip(fname):
            out.append(
                EpisodeIn(
                    channel=channel,
                    data=payload,
                    filename=f"{name}/{fname}",
                    sender=sender,
                    received_at=received,
                    meta={"attachment_of": name},
                    **kw,
                )
            )
    return out
