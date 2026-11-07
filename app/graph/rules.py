"""Rules API: the only way calculators and the answer pipeline read rule values.

    get_rule(session, topic, parameter, client=None)                 # what applies today
    get_rule(..., as_of=date(2026, 3, 1))                             # what applied on a date
    get_rule(..., known_at=datetime(...))                             # what we knew at a time

Missing rules raise RuleNotFound; there are no defaults (CLAUDE.md rule 2).
Expiry is applied on read: a claim whose invalid_at has passed is not current.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.models import Claim, Passage, Source
from app.core.pack import get_pack


class RuleNotFound(LookupError):
    pass


@dataclass(frozen=True)
class RuleValue:
    claim_id: int
    topic: str
    parameter: str
    client: str
    value: dict[str, Any]
    statement: str
    status: str
    source_id: str
    source_label: str
    locator: str | None
    passage_id: str | None
    valid_at: date | None
    invalid_at: date | None

    @property
    def number(self) -> float:
        n = self.value.get("number")
        if n is None:
            raise RuleNotFound(f"{self.topic}.{self.parameter} has no numeric value")
        return float(n)

    @property
    def citation(self) -> str:
        loc = self.locator or ""
        return (
            f"{self.source_label} §{loc}"
            if loc[:1].isdigit()
            else f"{self.source_label} {loc}".strip()
        )


_ROW = (Claim, Source.label, Source.kind, Passage.locator)


def _base(session: Session, topic: str, parameter: str, known_at: datetime | None):
    q = (
        select(*_ROW)
        .join(Source, Source.id == Claim.source_id)
        .outerjoin(Passage, Passage.id == Claim.passage_id)
        .where(Claim.topic == topic, Claim.parameter == parameter, Claim.kind != "practice")
        .where(~Claim.meta["retired"].as_boolean().is_(True))
    )
    if known_at is not None:
        q = q.where(
            Claim.created_at <= known_at,
            or_(Claim.expired_at.is_(None), Claim.expired_at > known_at),
        )
    return q


def _valid_on(d: date):
    return and_(
        or_(Claim.valid_at.is_(None), Claim.valid_at <= d),
        or_(Claim.invalid_at.is_(None), Claim.invalid_at >= d),
    )


def _to_value(row) -> RuleValue:
    c, label, _kind, locator = row
    return RuleValue(
        claim_id=c.id,
        topic=c.topic,
        parameter=c.parameter,
        client=c.scope.get("client", "all"),
        value=c.value,
        statement=c.statement,
        status=c.status,
        source_id=c.source_id,
        source_label=label,
        locator=locator,
        passage_id=c.passage_id,
        valid_at=c.valid_at,
        invalid_at=c.invalid_at,
    )


def _client_first(rows, client: str | None):
    """Client-specific claims override the general rule for that client only."""

    def scope_of(r) -> str:
        return r[0].scope.get("client", "all")

    specific = [r for r in rows if client and scope_of(r) == client]
    return specific or [r for r in rows if scope_of(r) == "all"]


def get_rule(
    session: Session,
    topic: str,
    parameter: str,
    client: str | None = None,
    as_of: date | None = None,
    known_at: datetime | None = None,
    today: date | None = None,
) -> RuleValue:
    q = _base(session, topic, parameter, known_at)
    if as_of is None:
        day = today or date.today()
        q = q.where(Claim.status.in_(("current", "provisional")), _valid_on(day))
        rows = _client_first(session.execute(q).all(), client)
        rows.sort(key=lambda r: (r[0].authority_rank, -(r[0].valid_at or date.min).toordinal()))
    else:
        # Audit view: what applied on that date, ranked by document kind (today's ranks
        # would wrongly put a then-current SOP below an old FAQ).
        q = q.where(
            Claim.status.in_(("current", "provisional", "superseded", "corroborating")),
            _valid_on(as_of),
        )
        rows = _client_first(session.execute(q).all(), client)
        order = {k: i for i, k in enumerate(get_pack().authority.get("kind_precedence", []))}
        rows.sort(
            key=lambda r: (
                order.get(r[2], 99),
                -(r[0].valid_at or date.min).toordinal(),
                r[0].authority_rank,
            )
        )
    if not rows:
        when = f" on {as_of}" if as_of else ""
        raise RuleNotFound(f"no rule for {topic}.{parameter} (client={client or 'all'}){when}")
    return _to_value(rows[0])


def older_claims(session: Session, topic: str, client: str | None = None) -> list[RuleValue]:
    """Superseded claims for a topic, for the answer card's older_sources."""
    q = (
        select(*_ROW)
        .join(Source, Source.id == Claim.source_id)
        .outerjoin(Passage, Passage.id == Claim.passage_id)
        .where(Claim.topic == topic, Claim.status == "superseded")
        .where(~Claim.meta["retired"].as_boolean().is_(True))
    )
    rows = [
        r for r in session.execute(q).all() if r[0].scope.get("client", "all") in ("all", client)
    ]
    return [_to_value(r) for r in rows]


def expert_tips(session: Session, topic: str, client: str | None = None) -> list[RuleValue]:
    q = (
        select(*_ROW)
        .join(Source, Source.id == Claim.source_id)
        .outerjoin(Passage, Passage.id == Claim.passage_id)
        .where(Claim.topic == topic, Claim.kind == "practice", Claim.status == "current")
    )
    rows = [
        r for r in session.execute(q).all() if r[0].scope.get("client", "all") in ("all", client)
    ]
    return [_to_value(r) for r in rows]
