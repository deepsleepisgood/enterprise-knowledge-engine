"""The knowledge base's history, one step per episode in the order it arrived (for replay).

Each step reports what the engine learned when that episode was processed: rules it replaced
(the winner's `supersedes_id` names the loser), statements it brought that a better source
already outranks, facts held for review, and how many rules were in force once it was done.
Everything is read from the bitemporal tables; nothing is recomputed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, aliased

from app.store.base import tenant
from app.store.models import Change, Entity, Episode, Fact, Job, Source

LIST_LIMIT = 12  # rows per list in one step; the rest are counted


@dataclass
class Swap:
    subject: str
    attribute: str
    old: str
    old_source: str | None
    new: str
    new_source: str | None
    valid_from: datetime | None


@dataclass
class Step:
    episode_id: str
    file: str
    status: str
    sources: list[dict[str, Any]]
    arrived_at: datetime
    done_at: datetime | None  # the instant to ask "as known then"; None while processing
    facts: int = 0  # live facts this episode produced
    rules_in_force: int = 0  # current facts once the step was done
    replaced: list[Swap] = field(default_factory=list)
    replaced_total: int = 0
    outranked: list[Swap] = field(default_factory=list)  # new statement lost to a better source
    outranked_total: int = 0
    held: list[str] = field(default_factory=list)  # pending or provisional statements
    held_total: int = 0
    announced: list[str] = field(default_factory=list)  # change notices this episode published


def value_text(v: dict[str, Any] | None, fallback: str = "") -> str:
    """A fact value as a short readable string."""
    v = v or {}
    n = v.get("number")
    if n is not None:
        num = f"{float(n):,.6g}" if abs(float(n)) < 1e6 else f"{float(n):,.0f}"
        unit = (v.get("unit") or "").strip()
        if unit in ("%", "percent", "pct"):
            return f"{num}%"
        return f"{num} {unit}".strip()
    if v.get("items"):
        return ", ".join(str(x) for x in v["items"])
    if v.get("date"):
        return str(v["date"])
    text = (v.get("text") or fallback or "").strip()
    return text if len(text) <= 140 else text[:137] + "…"


def _numeric(sw: Swap) -> bool:
    """A short value change with figures on both sides (a limit, a rate, a threshold)."""
    digits = any(c.isdigit() for c in sw.old) and any(c.isdigit() for c in sw.new)
    return digits and len(sw.new) < 30


def _episodes(session: Session) -> list[Episode]:
    q = select(Episode).where(Episode.tenant_id == tenant()).order_by(Episode.created_at)
    return list(session.scalars(q))


def busy(session: Session) -> int:
    """Jobs still queued or running for this tenant."""
    return int(
        session.scalar(
            select(func.count()).where(
                Job.tenant_id == tenant(), Job.status.in_(["queued", "running"])
            )
        )
        or 0
    )


def last_write(session: Session) -> datetime | None:
    t = tenant()
    a = session.scalar(select(func.max(Fact.recorded_at)).where(Fact.tenant_id == t))
    b = session.scalar(select(func.max(Fact.retracted_at)).where(Fact.tenant_id == t))
    return max((x for x in (a, b) if x), default=None)


def _num_changed(new: Fact, old: Fact) -> bool:
    a, b = (old.value or {}).get("number"), (new.value or {}).get("number")
    return a is not None and b is not None and float(a) != float(b)


def _alive(model: Any, at: datetime | None) -> list[Any]:
    """Rows the engine held at `at` (None: now)."""
    if at is None:
        return [model.retracted_at.is_(None)]
    return [model.recorded_at <= at, or_(model.retracted_at.is_(None), model.retracted_at > at)]


def _swap(new: Fact, old: Fact, names: dict[str, str], labels: dict[str, str]) -> Swap:
    return Swap(
        subject=names.get(new.subject_id, ""),
        attribute=new.attribute,
        old=value_text(old.value, old.statement),
        old_source=labels.get(old.source_id),
        new=value_text(new.value, new.statement),
        new_source=labels.get(new.source_id),
        valid_from=new.valid_from,
    )


def steps(session: Session, processing: bool = False) -> list[Step]:
    """One step per episode, oldest first. `processing`: the newest step is still running."""
    t = tenant()
    eps = _episodes(session)
    if not eps:
        return []
    srcs: dict[str, list[Source]] = {}
    for src in session.scalars(
        select(Source).where(Source.tenant_id == t).order_by(Source.ordinal)
    ):
        srcs.setdefault(src.episode_id, []).append(src)
    labels = {s.id: s.short_label for ss in srcs.values() for s in ss}
    names = dict(session.execute(select(Entity.id, Entity.name).where(Entity.tenant_id == t)).all())
    end = last_write(session)
    out: list[Step] = []
    for i, ep in enumerate(eps):
        nxt = eps[i + 1].created_at if i + 1 < len(eps) else None
        if nxt is not None:
            done_at = nxt - timedelta(microseconds=1)
        elif processing:
            done_at = None
        else:
            done_at = max(x for x in (end, ep.created_at) if x)
        # Every list reads the facts as they stood when the step was done (still running: now).
        mine = (Fact.tenant_id == t, Fact.episode_id == ep.id, *_alive(Fact, done_at))
        step = Step(
            episode_id=ep.id,
            file=ep.source_uri or ep.id,
            status=ep.status,
            sources=[
                {
                    "label": s.short_label,
                    "doc_type": s.doc_type,
                    "dated": s.dated,
                    "status": s.status,
                }
                for s in srcs.get(ep.id, [])
            ],
            arrived_at=ep.created_at,
            done_at=done_at,
            facts=int(session.scalar(select(func.count()).where(*mine)) or 0),
        )
        step.rules_in_force = int(
            session.scalar(
                select(func.count()).where(
                    Fact.tenant_id == t, Fact.status == "current", *_alive(Fact, done_at)
                )
            )
            or 0
        )
        step.announced = list(
            session.scalars(
                select(Change.summary)
                .where(
                    Change.tenant_id == t,
                    Change.source_episode == ep.id,
                    Change.new_fact.is_not(None),
                )
                .order_by(Change.id)
            )
        )
        # Rules this episode replaced: its winners and the facts they superseded.
        old = aliased(Fact)
        rows = session.execute(
            select(Fact, old)
            .join(old, old.id == Fact.supersedes_id)
            .where(*mine, Fact.supersedes_id.is_not(None))
            .order_by(Fact.attribute)
        ).all()
        # The same source restating itself counts only when a number changed (a dated update).
        rows = [(n, o) for n, o in rows if n.source_id != o.source_id or _num_changed(n, o)]
        swaps = [_swap(n, o, names, labels) for n, o in rows]
        swaps = [x for x in swaps if x.old != x.new]
        swaps.sort(key=lambda x: (not _numeric(x), x.attribute))  # changed numbers first
        step.replaced_total = len(swaps)
        step.replaced = swaps[:LIST_LIMIT]
        # Statements this episode brought that a better-ranked other source outranked.
        lost = list(
            session.scalars(
                select(Fact).where(*mine, Fact.status == "overridden").order_by(Fact.attribute)
            )
        )
        outranked = []
        for f in lost:
            win = session.scalar(
                select(Fact)
                .where(
                    Fact.tenant_id == t,
                    Fact.subject_id == f.subject_id,
                    Fact.attribute == f.attribute,
                    Fact.status == "current",
                    Fact.source_id != f.source_id,
                    *_alive(Fact, done_at),
                )
                .order_by(Fact.authority_rank)
                .limit(1)
            )
            if win is not None:
                outranked.append(_swap(win, f, names, labels))
        step.outranked_total = len(outranked)
        step.outranked = outranked[:LIST_LIMIT]
        held = list(
            session.scalars(
                select(Fact.statement).where(*mine, Fact.status.in_(["pending", "provisional"]))
            )
        )
        step.held_total = len(held)
        step.held = held[:LIST_LIMIT]
        out.append(step)
    return out
