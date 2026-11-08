"""Authority resolution (BUILD_PLAN Phase 2d): which assertion holds in each (subject, attribute).

Pure function over `Assertion`s, so precedence is unit-tested without a database. It is run on
one (subject, attribute) group at a time, with only that group's facts (CLAUDE.md rule 12).

1. Scope: assertions are bucketed by client. A client-scoped fact overrides the general rule
   for that client only; the general bucket is never touched by a client bucket.
2. Within a bucket, the lowest authority_rank among sources with status `current` wins (ties:
   the later start). Authority beats recency: a newer fact from a lower-ranked source loses.
3. Same value (or narrower scope) from another source: `corroborating`. Complementary values
   are one list, not a conflict: among equally ranked assertions the one whose items cover the
   others wins, and an assertion whose items are part of the winner's list corroborates it
   (a source stating "Tuesday" and "Friday" separately and "Tuesday and Friday" in a summary).
4. Different value: `superseded`, valid until the day before the winner starts; if it did not
   start earlier than the winner, `overridden` with an empty interval (kept for audit). Two
   current sources that disagree also open a `value` conflict.
5. Practice never overrides a rule: it stays `current` as a tip; a contradiction opens a
   `practice_vs_rule` conflict.
6. No current source in a bucket: facts from superseded sources are `superseded` (their source's
   validity ends them); others are `pending` for the owner, unless a general rule settles them.
Validity is a closed-open day interval [valid_from, valid_to); `None` is unbounded.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Literal

Verdict = Literal["same", "different", "narrower", "unknown"]
AUTHORITATIVE = {"current"}


@dataclass
class Assertion:
    key: str
    subject_id: str
    attribute: str
    client: str  # canonical client name or "all"
    value: dict[str, Any]
    kind: str
    statement: str
    source_id: str
    source_label: str
    source_status: str
    authority_rank: int
    asserted_from: date | None
    asserted_to: date | None  # last day in force (inclusive), from the fact or its source
    scope: dict[str, Any] = field(default_factory=dict)
    position: int = 0  # passage order in its source: ties go to where the rule is first stated
    # set by resolution
    status: str = "pending"
    valid_from: date | None = None
    valid_to: date | None = None  # exclusive
    supersedes_key: str | None = None
    reason: str = ""


@dataclass
class ConflictRec:
    subject_id: str
    attribute: str
    client: str
    a_key: str
    b_key: str
    kind: str
    authoritative_key: str | None
    reason: str


Comparator = Callable[[Assertion, Assertion], Verdict]


def _end(a: Assertion) -> date | None:
    return a.asserted_to + timedelta(days=1) if a.asserted_to else None


def _winner_key(a: Assertion) -> tuple[int, int]:
    return (a.authority_rank, -(a.asserted_from.toordinal() if a.asserted_from else 0))


def _items(a: Assertion) -> set[str]:
    v = a.value or {}
    raw = v.get("items") or ([v["text"]] if v.get("text") else [])
    return {" ".join(str(x).lower().split()) for x in raw if str(x).strip()}


def _part_of(small: Assertion, big: Assertion) -> bool:
    """`small`'s items are all in `big`'s list (and `big` is a list of more than one)."""
    s, b = _items(small), _items(big)
    return bool(s) and len(b) > 1 and s <= b


def _pick(eligible: list[Assertion]) -> Assertion:
    """Highest authority (then latest start); among those, the widest list, then the
    statement that comes first in its document (a rule section before its summary table).
    A statement that defers to another eligible source ("per Client Memo CM-X-01") does not
    win over that source."""
    own = [a for a in eligible if _defers_to(a, eligible) is None] or eligible
    best = min(_winner_key(a) for a in own)
    top = [a for a in own if _winner_key(a) == best]
    return max(top, key=lambda a: (len(_items(a)), -a.position))


def _defers_to(a: Assertion, others: list[Assertion]) -> Assertion | None:
    """The other source that `a` names as where the rule is stated, if one is in the group."""
    v = a.value or {}
    text = " ".join(str(x) for x in [v.get("text") or "", *(v.get("items") or [])]).lower()
    for b in others:
        label = (b.source_label or "").lower()
        if b.source_id != a.source_id and len(label) >= 4 and label in text:
            return b
    return None


def _keep(a: Assertion, status: str, reason: str) -> None:
    a.status, a.reason = status, reason
    a.valid_from, a.valid_to = a.asserted_from, _end(a)


def _retire(loser: Assertion, winner: Assertion, why: str) -> None:
    loser.reason = why
    loser.valid_from = loser.asserted_from
    if winner.asserted_from and (
        loser.asserted_from is None or loser.asserted_from < winner.asserted_from
    ):
        loser.status = "superseded"
        end = _end(loser)
        loser.valid_to = min(winner.asserted_from, end) if end else winner.asserted_from
    elif winner.asserted_from is None:
        loser.status, loser.valid_to = "superseded", loser.asserted_from
    else:
        loser.status = "overridden"  # never in force: the winner started first
        loser.valid_to = loser.asserted_from
    if winner.supersedes_key is None:
        winner.supersedes_key = loser.key


def _settle(
    others: list[Assertion], winner: Assertion, compare: Comparator, conflicts: list[ConflictRec]
) -> None:
    for o in sorted(others, key=_winner_key):
        if _part_of(o, winner):
            _keep(o, "corroborating", f"part of the list in {winner.source_label}")
            continue
        verdict = compare(o, winner)
        if verdict in ("same", "narrower"):
            _keep(o, "corroborating", f"agrees with {winner.source_label}")
            continue
        current = o.source_status in AUTHORITATIVE
        if verdict == "unknown" and current:
            _keep(o, "corroborating", f"current source; wording differs from {winner.source_label}")
            continue
        _retire(o, winner, f"{winner.source_label} (rank {winner.authority_rank}) takes precedence")
        if current and verdict == "different":
            conflicts.append(
                ConflictRec(
                    winner.subject_id,
                    winner.attribute,
                    winner.client,
                    winner.key,
                    o.key,
                    "value",
                    winner.key,
                    f"Both sources are current; {winner.source_label} has higher authority.",
                )
            )


def resolve_group(group: list[Assertion], compare: Comparator) -> list[ConflictRec]:
    conflicts: list[ConflictRec] = []
    rules = [a for a in group if a.kind != "practice"]
    practices = [a for a in group if a.kind == "practice"]
    buckets: dict[str, list[Assertion]] = defaultdict(list)
    for a in rules:
        buckets[a.client].append(a)
    winners: dict[str, Assertion] = {}
    for client in sorted(buckets, key=lambda k: (k != "all", k)):
        bucket = buckets[client]
        eligible = [a for a in bucket if a.source_status in AUTHORITATIVE]
        if eligible:
            w = _pick(eligible)
            _keep(
                w,
                "current",
                "highest-authority current source" + (f" for {client}" if client != "all" else ""),
            )
            winners[client] = w
            _settle([a for a in bucket if a is not w], w, compare, conflicts)
        elif client != "all" and "all" in winners:
            _settle(bucket, winners["all"], compare, conflicts)
        else:
            for a in bucket:
                if a.source_status == "superseded":
                    _keep(a, "superseded", f"{a.source_label} is superseded")
                else:
                    _keep(a, "pending", "no current source states this; needs owner review")
    for p in practices:
        _keep(p, "current", "expert practice (a tip; never overrides a rule)")
        rule = winners.get(p.client) or winners.get("all")
        if rule is not None and compare(p, rule) == "different":
            conflicts.append(
                ConflictRec(
                    p.subject_id,
                    p.attribute,
                    p.client,
                    rule.key,
                    p.key,
                    "practice_vs_rule",
                    rule.key,
                    f"Practice in {p.source_label} differs from {rule.source_label}.",
                )
            )
    return conflicts


def resolve(assertions: list[Assertion], compare: Comparator) -> list[ConflictRec]:
    groups: dict[tuple[str, str], list[Assertion]] = defaultdict(list)
    for a in assertions:
        groups[(a.subject_id, a.attribute)].append(a)
    out: list[ConflictRec] = []
    for g in groups.values():
        out += resolve_group(g, compare)
    return out
