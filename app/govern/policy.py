"""Governance (BUILD_PLAN Phase 9, SCOPE section 2): a process owner verifies every new or
changed rule that arrives after the knowledge base is set up.

    sender registered for the scope, every topic low or normal risk  -> provisional
        (answerable at once, labelled provisional, queued for the owner to confirm)
    anyone else, or any high-risk topic                              -> pending
        (not applied; nothing in force changes until the owner approves)

The sender-authority map and the risk tiers come from the tenant's frozen schema (induced and
confirmed by the owner on the Setup page); nothing here is specific to a company.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.graph.ontology import Ontology

PROVISIONAL, PENDING = "provisional", "pending"


def _norm(x: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (x or "").lower()).strip()


def _matches(who: str, sender: str | None, role: str | None) -> bool:
    w = _norm(who)
    if not w:
        return False
    for x in (_norm(sender), _norm(role)):
        if x and (w == x or (len(w) > 3 and w in x) or (len(x) > 3 and x in w)):
            return True
    return False


def same_client(granted: str | None, client: str | None) -> bool:
    """A grant's client names the same client ('Acme Retail' ~ 'Acme Retail Pvt Ltd')."""
    g, c = _norm(granted), _norm(client)
    if not g or not c:
        return False
    return g == c or (len(g) > 3 and (c.startswith(g + " ") or g.startswith(c + " ")))


def owns_client(onto: Ontology, sender: str | None, role: str | None, client: str | None) -> bool:
    """The sender is registered as the owner of this one client's scope (not a global grant)."""
    return any(
        _norm(a.client) != "all" and same_client(a.client, client) and _matches(a.who, sender, role)
        for a in onto.sender_authority
    )


@dataclass
class Verdict:
    status: str  # provisional | pending
    reasons: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    high_risk: list[str] = field(default_factory=list)


def decide(
    onto: Ontology,
    sender: str | None,
    sender_role: str | None,
    topics: set[str],
    clients: set[str],
) -> Verdict:
    """Provisional or pending for one episode's facts (`clients` uses 'all' for general rules)."""
    topics = {t for t in topics if t}
    high = sorted(t for t in topics if onto.risk_of(t) == "high")
    grants = [a for a in onto.sender_authority if _matches(a.who, sender, sender_role)]
    reasons: list[str] = []
    if high:
        reasons.append("high-risk topic: " + ", ".join(high))
    if not grants:
        who = sender_role or sender or "an unknown sender"
        reasons.append(f"{who} is not a registered owner for these topics")
    else:
        for t in sorted(topics):
            ok_topic = [a for a in grants if "all" in a.topics or t in a.topics]
            if not ok_topic:
                reasons.append(f"{sender_role or sender} may not change {t}")
                continue
            for c in sorted(clients):
                if not any(a.client == "all" or same_client(a.client, c) for a in ok_topic):
                    reasons.append(f"{sender_role or sender} may not change {t} for {c}")
    status = PENDING if reasons else PROVISIONAL
    if not reasons:
        reasons.append("registered sender, own scope, no high-risk topic")
    return Verdict(status, reasons, sorted(topics), high)


def change_payload(
    episode: Any, verdict: Verdict, source_ids: list[str], facts: list[Any], labels: list[str]
) -> dict[str, Any]:
    """The review item for a held change (shown in the owner's Review queue)."""
    where = ", ".join(labels) or episode.source_uri or "an input"
    state = "held" if verdict.status == PENDING else "provisional"
    return {
        "summary": f"{len(facts)} {'fact' if len(facts) == 1 else 'facts'} from {where} "
        f"{'is' if len(facts) == 1 else 'are'} {state} for your decision",
        "episode_id": episode.id,
        "channel": episode.channel,
        "sender": episode.sender,
        "sender_role": episode.sender_role,
        "status": verdict.status,
        "reasons": verdict.reasons,
        "topics": verdict.topics,
        "high_risk": verdict.high_risk,
        "source_ids": source_ids,
        "fact_ids": [f.id for f in facts],
        "facts": [
            {
                "statement": f.statement,
                "attribute": f.attribute,
                "client": (f.scope or {}).get("client") or "all",
                "valid_from": f.valid_from.date().isoformat() if f.valid_from else None,
            }
            for f in facts[:25]
        ],
    }
