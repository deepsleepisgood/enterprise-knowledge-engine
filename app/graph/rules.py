"""Rule lookups over the fact graph (BUILD_PLAN Phase 2e). Plug-ins read thresholds only here.

    get_rule(session, onto, "price_tolerance", "pct_of_line", client="Northwind", as_of=d)

Current mode (no `as_of`): facts valid today with status current or provisional; the
client-specific fact wins over the general one. `as_of`: facts valid on that day whose status
says they were in force then (current, superseded, provisional), ranked by source authority.
`known_at`: what the engine believed at that instant (transaction time).
A missing rule raises `RuleNotFound`; there is never a default.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.graph.ontology import Ontology
from app.store import entities as ent
from app.store import episodes as estore
from app.store import facts as fstore
from app.store.base import last_day, utcnow

_LIST_SEP = re.compile(r"\s*(?:,|;|&|\band\b)\s*", re.I)

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
            # "20% or the applicable rate, whichever is higher": the rule's own figure is its
            # one percentage (how it combines with other rules is the caller's logic).
            pcts = re.findall(r"(\d+(?:\.\d+)?)\s*(?:%|per ?cent)", self.text, re.I)
            if len(set(pcts)) == 1:
                return float(pcts[0])
            if not pcts and re.match(r"\s*(none|nil|zero)\b", self.text, re.I):
                return 0.0  # "None, except client memo CM-X-02": no tolerance in general
            raise RuleNotFound(f"{self.attribute} has no numeric value ({self.value.get('text')})")
        return float(n)

    @property
    def text(self) -> str:
        return str(self.value.get("text") or "")

    @property
    def items(self) -> list[str]:
        """The listed values. A list written as one phrase ("Tuesday and Friday") is split."""
        if self.value.get("items"):
            return list(self.value["items"])
        if (self.value.get("type") or "").lower() not in ("list", "enum"):
            return []
        parts = [p.strip() for p in _LIST_SEP.split(self.text) if p.strip()]
        return parts if len(parts) > 1 else []

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
    if known_at is None:
        rows = _within_source_life(session, rows, day)
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
            if scope_client is None and name and (best.value or {}).get("number") is None:
                ref = _referenced_rule(session, best, attr, name, day, known_at, statuses)
                if ref is not None:
                    return _to_value(ref)
            return _to_value(best)
    where = f" for {client}" if client else ""
    when = f" on {day}" if as_of else ""
    raise RuleNotFound(f"no rule in force for {attr}{where}{when}")


def _within_source_life(
    session: Session, rows: list[fstore.FactRow], day: date
) -> list[fstore.FactRow]:
    """Drop facts whose document had ended by `day` (e.g. an SOP version replaced by a newer
    one). Its facts stay open until the owner retires them, but a document past its last day
    is never the rule in force. Source end dates are not bitemporal, so this applies to what
    the engine believes now only (known_at=None)."""
    ends = estore.last_days(session, {r.source_id for r in rows if r.source_id})
    return [r for r in rows if not (r.source_id in ends and ends[r.source_id] < day)]


def _tokens(s: str) -> set[str]:
    return {w for w in re.split(r"[^a-z]+", s.lower()) if len(w) > 2}


def _referenced_rule(
    session: Session,
    general: fstore.FactRow,
    attr: str,
    client: str,
    day: date,
    known_at: datetime | None,
    statuses: list[str],
) -> fstore.FactRow | None:
    """A general rule with no figure that defers to a named source for some clients ("None,
    except client memo CM-INF-02"): that source's numeric rule for this client, filed under the
    attribute closest in name to the one asked for."""
    v = general.value or {}
    text = " ".join([str(v.get("text") or ""), general.condition or "", general.statement])
    rows = fstore.get_facts(session, valid_on=day, known_at=known_at, statuses=statuses)
    want = _tokens(attr)
    best: tuple[int, fstore.FactRow] | None = None
    for r in rows:
        label = r.source_label or ""
        if (
            r.kind == "practice"
            or (r.value or {}).get("number") is None
            or ((r.scope or {}).get("client") or None) != client
            or len(label) < 4
            or label.lower() not in text.lower()
        ):
            continue
        score = len(want & _tokens(r.attribute))
        if score and (best is None or score > best[0]):
            best = (score, r)
    return best[1] if best else None


def older_values(session: Session, attribute: str, client: str | None = None) -> list[RuleValue]:
    """Superseded and overridden facts for the 'older sources' line (never as the answer)."""
    name = canonical_client(session, client)
    rows = fstore.get_facts(session, attribute=attribute, statuses=["superseded", "overridden"])
    return [_to_value(r) for r in rows if ((r.scope or {}).get("client") or None) in (None, name)]


def expert_tips(session: Session, attribute: str) -> list[RuleValue]:
    rows = fstore.get_facts(session, attribute=attribute, statuses=["current"], kinds=["practice"])
    return [_to_value(r) for r in rows]
