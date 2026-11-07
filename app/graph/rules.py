"""Rule lookups over the fact graph (BUILD_PLAN Phase 2e). Plug-ins read thresholds only here.

    get_rule(session, onto, "price_tolerance", "pct_of_line", client="Northwind", as_of=d)

Current mode (no `as_of`): facts valid today with status current or provisional; the
client-specific fact wins over the general one. `as_of`: facts valid on that day whose status
says they were in force then (current, superseded, provisional), ranked by source authority.
`known_at`: what the engine believed at that instant (transaction time).
A missing rule raises `RuleNotFound`; there is never a default.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.graph.ontology import Ontology
from app.store import entities as ent
from app.store import facts as fstore
from app.store.base import last_day, utcnow

CURRENT = ["current", "provisional"]
IN_FORCE_THEN = ["current", "superseded", "provisional"]


class RuleNotFound(LookupError):
    pass


@dataclass
class RuleValue:
    fact_id: int
    attribute: str
    client: str | None
    value: dict[str, Any]
    statement: str
    status: str
    source_id: str | None
    source_label: str | None
    locator: str | None
    passage_id: str | None
    valid_from: date | None
    valid_until: date | None  # last day in force
    condition: str | None = None

    @property
    def number(self) -> float:
        n = self.value.get("number")
        if n is None:
            raise RuleNotFound(f"{self.attribute} has no numeric value ({self.value.get('text')})")
        return float(n)

    @property
    def text(self) -> str:
        return str(self.value.get("text") or "")

    @property
    def items(self) -> list[str]:
        return list(self.value.get("items") or [])

    @property
    def citation(self) -> str:
        return f"{self.source_label} {self.locator}".strip()


def resolve_attribute(onto: Ontology, topic: str, parameter: str) -> str:
    key = f"{topic}.{parameter}"
    if onto.attribute(key):
        return key
    raise RuleNotFound(f"attribute {key} is not in the schema")


def canonical_client(session: Session, client: str | None) -> str | None:
    """The canonical name of a client as the graph knows it (alias, else a close name match)."""
    if not client or client == "all":
        return None
    eid = ent.by_alias(session, client, "client")
    if eid is None:
        from app.graph.entities import name_similarity

        cands = [
            c
            for c in ent.candidates(session, client, "client")
            if max(name_similarity(client, a) for a in [c.name, *c.aliases]) >= 0.85
        ]
        if len(cands) == 1 or (cands and cands[0].score > cands[1].score):
            eid = cands[0].id
    if eid is None:
        return client
    row = ent.get(session, eid)
    return row.name if row else client


def _to_value(r: fstore.FactRow) -> RuleValue:
    return RuleValue(
        fact_id=r.id,
        attribute=r.attribute,
        client=(r.scope or {}).get("client"),
        value=r.value,
        statement=r.statement,
        status=r.status,
        source_id=r.source_id,
        source_label=r.source_label,
        locator=r.locator,
        passage_id=r.passage_id,
        valid_from=r.valid_from.date() if r.valid_from else None,
        valid_until=last_day(r.valid_to),
        condition=r.condition,
    )


def get_rule(
    session: Session,
    onto: Ontology,
    topic: str,
    parameter: str,
    client: str | None = None,
    as_of: date | None = None,
    known_at: datetime | None = None,
    today: date | None = None,
    attribute: str | None = None,
) -> RuleValue:
    attr = attribute or resolve_attribute(onto, topic, parameter)
    day = as_of or today or utcnow().date()
    statuses = IN_FORCE_THEN if as_of else CURRENT
    rows = [
        r
        for r in fstore.get_facts(
            session, attribute=attr, valid_on=day, known_at=known_at, statuses=statuses
        )
        if r.kind != "practice"
    ]
    name = canonical_client(session, client)
    for scope_client in ([name] if name else []) + [None]:
        hits = [r for r in rows if ((r.scope or {}).get("client") or None) == scope_client]
        if hits:
            best = min(
                hits,
                key=lambda r: (
                    r.authority_rank,
                    -(r.valid_from.timestamp() if r.valid_from else 0),
                ),
            )
            return _to_value(best)
    where = f" for {client}" if client else ""
    when = f" on {day}" if as_of else ""
    raise RuleNotFound(f"no rule in force for {attr}{where}{when}")


def older_values(session: Session, attribute: str, client: str | None = None) -> list[RuleValue]:
    """Superseded and overridden facts for the 'older sources' line (never as the answer)."""
    name = canonical_client(session, client)
    rows = fstore.get_facts(session, attribute=attribute, statuses=["superseded", "overridden"])
    return [_to_value(r) for r in rows if ((r.scope or {}).get("client") or None) in (None, name)]


def expert_tips(session: Session, attribute: str) -> list[RuleValue]:
    rows = fstore.get_facts(session, attribute=attribute, statuses=["current"], kinds=["practice"])
    return [_to_value(r) for r in rows]
