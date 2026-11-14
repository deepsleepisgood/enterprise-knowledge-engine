"""Sending the daily digest: now (from the digest card) or automatically once a day.

With DIGEST_SEND_AT set ("HH:MM" in the team's time zone, DIGEST_UTC_OFFSET_MINUTES east of
UTC) and at least one channel set up, the worker queues one `digest_send` job per local day once
that time has passed. The job sends the day's team digest (no per-user lines) on every set-up
channel; on a day without changes it sends nothing unless DIGEST_SKIP_EMPTY is false. The job row
is the send log (its result lists each channel), and its day makes the send happen once.
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import session_scope
from app.distribute import channels
from app.distribute.digest import build_digest
from app.store import answers as astore
from app.store import jobs
from app.store.base import use_tenant, utcnow
from app.worker import handler

log = logging.getLogger("digest")
KIND = "digest_send"
TICK_S = 60


def team_digest(session: Session, day: date, utc_offset_minutes: int) -> dict[str, Any]:
    """The day's digest for the whole team (no per-user acknowledgement lines)."""
    return build_digest(session, day, utc_offset_minutes, None, astore.distinct_users(session))


def send(
    session: Session,
    day: date,
    utc_offset_minutes: int,
    which: list[str] | None = None,
    **transports: Any,
) -> dict[str, Any]:
    d = team_digest(session, day, utc_offset_minutes)
    return {"day": day.isoformat(), "results": channels.deliver(d, which, **transports)}


def due_day(now: datetime, send_at: str, utc_offset_minutes: int) -> date | None:
    """The local day whose digest is due at `now` (UTC), or None before the send time."""
    at = channels.parse_send_at(send_at)
    if at is None:
        return None
    local = now + timedelta(minutes=utc_offset_minutes)
    if (local.hour, local.minute) < at:
        return None
    return local.date()


def schedule_tick(session: Session, now: datetime | None = None) -> int | None:
    """Queue today's digest send if it is due and not queued yet. Returns the job id."""
    s = get_settings()
    if not (channels.email_configured(s) or channels.teams_configured(s)):
        return None
    day = due_day(now or utcnow(), s.digest_send_at, s.digest_utc_offset_minutes)
    if day is None or jobs.exists_with(session, KIND, "day", day.isoformat()):
        return None
    payload = {"day": day.isoformat(), "utc_offset_minutes": s.digest_utc_offset_minutes}
    # One attempt: a retry after a partial send would email people twice.
    return jobs.enqueue(session, KIND, payload, max_attempts=1)


@handler(KIND)
def run(payload: dict[str, Any]) -> dict[str, Any]:
    s = get_settings()
    day = date.fromisoformat(payload["day"])
    with session_scope() as session:
        d = team_digest(session, day, int(payload.get("utc_offset_minutes", 0)))
    if d["empty"] and s.digest_skip_empty:
        return {"day": day.isoformat(), "skipped": "no changes on this day", "results": []}
    results = channels.deliver(d)
    if results and not any(r["ok"] for r in results):
        raise RuntimeError("; ".join(f"{r['channel']}: {r['detail']}" for r in results))
    return {"day": day.isoformat(), "results": results}


def loop() -> None:  # pragma: no cover - long-running
    """The worker's daily-send clock (the configured tenant)."""
    s = get_settings()
    while True:
        try:
            with use_tenant(s.tenant_id), session_scope() as session:
                job = schedule_tick(session)
            if job:
                log.info("queued the daily digest send (job %s)", job)
        except Exception as exc:  # the database blinked: try again next tick
            log.warning("digest schedule: %s", exc)
        time.sleep(TICK_S)
